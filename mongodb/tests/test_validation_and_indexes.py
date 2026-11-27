"""Schema validation and indexes, checked against the server itself."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, WriteError

DOCUMENT_VALIDATION_FAILURE = 121  # MongoDB's error code for a $jsonSchema rejection


def test_validator_rejects_a_document_missing_a_required_field(db: Database[dict[str, Any]]) -> None:
    with pytest.raises(WriteError) as caught:
        db.contacts.insert_one({"owner": "alice", "name": "No email", "created_at": datetime.now(UTC)})

    assert caught.value.code == DOCUMENT_VALIDATION_FAILURE
    assert db.contacts.count_documents({}) == 0


def test_validator_rejects_a_wrong_type(db: Database[dict[str, Any]]) -> None:
    # created_at as a string: easy to do by accident from JSON, and it would silently
    # break the date queries and the TTL index.
    with pytest.raises(WriteError) as caught:
        db.contacts.insert_one(
            {"owner": "alice", "name": "Ana", "email": "ana@example.com", "created_at": "2026-01-01"}
        )
    assert caught.value.code == DOCUMENT_VALIDATION_FAILURE


def test_api_surfaces_validator_rejections_as_422(api: str, db: Database[dict[str, Any]]) -> None:
    response = requests.post(
        f"{api}/contacts", json={"owner": "alice", "name": "Ana", "email": "not-an-email"}, timeout=10
    )
    assert response.status_code == 422
    assert db.contacts.count_documents({}) == 0


def test_unique_index_rejects_a_duplicate_email(api: str, db: Database[dict[str, Any]]) -> None:
    body = {"owner": "alice", "name": "Ana", "email": "ana@example.com"}
    assert requests.post(f"{api}/contacts", json=body, timeout=10).status_code == 201

    duplicate = requests.post(f"{api}/contacts", json=body | {"owner": "bob"}, timeout=10)

    assert duplicate.status_code == 409
    assert db.contacts.count_documents({}) == 1
    with pytest.raises(DuplicateKeyError):  # and directly, without the API
        db.contacts.insert_one(body | {"created_at": datetime.now(UTC)})


# --- Are the indexes actually used? ----------------------------------------------------


def plan_values(plan: Any, key: str) -> list[Any]:
    """Every value of `key` anywhere in an explain() plan tree.

    Plans nest (FETCH -> IXSCAN, and MongoDB 8 wraps them in "queryPlan"), so walk the
    whole tree instead of hard-coding one shape.
    """
    if isinstance(plan, dict):
        found = [plan[key]] if key in plan else []
        return found + [value for child in plan.values() for value in plan_values(child, key)]
    if isinstance(plan, list):
        return [value for child in plan for value in plan_values(child, key)]
    return []


@pytest.fixture
def some_contacts(db: Database[dict[str, Any]]) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    db.contacts.insert_many(
        {
            "owner": owner,
            "name": f"{owner} {n}",
            "email": f"{owner}{n}@example.com",
            "created_at": start + timedelta(days=n),
        }
        for owner in ("alice", "bob")
        for n in range(20)
    )


@pytest.mark.usefixtures("some_contacts")
def test_lookup_by_email_uses_the_unique_index(db: Database[dict[str, Any]]) -> None:
    plan = db.contacts.find({"email": "alice3@example.com"}).explain()["queryPlanner"]["winningPlan"]

    assert "IXSCAN" in plan_values(plan, "stage")
    assert "COLLSCAN" not in plan_values(plan, "stage")
    assert plan_values(plan, "indexName") == ["email_unique"]


@pytest.mark.usefixtures("some_contacts")
def test_owner_newest_first_uses_the_compound_index_without_sorting(db: Database[dict[str, Any]]) -> None:
    cursor = db.contacts.find({"owner": "alice"}).sort("created_at", -1)
    plan = cursor.explain()["queryPlanner"]["winningPlan"]

    assert plan_values(plan, "indexName") == ["owner_created_at"]
    # The index is already in (owner, created_at desc) order: no in-memory SORT stage.
    assert "SORT" not in plan_values(plan, "stage")


@pytest.mark.usefixtures("some_contacts")
def test_unindexed_query_is_a_collection_scan(db: Database[dict[str, Any]]) -> None:
    # The control case: proves the helper can tell the difference.
    plan = db.contacts.find({"name": "alice 3"}).explain()["queryPlanner"]["winningPlan"]
    assert plan_values(plan, "stage") == ["COLLSCAN"]
