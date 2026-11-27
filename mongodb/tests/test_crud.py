"""CRUD round-trips: write through the API, then look at the collection directly."""

from datetime import datetime
from typing import Any

import requests
from bson import ObjectId
from pymongo.database import Database

ALICE = {"owner": "alice", "name": "Ana Lima", "email": "ana@example.com"}


def create(api: str, body: dict[str, Any]) -> requests.Response:
    return requests.post(f"{api}/contacts", json=body, timeout=10)


def test_create_stores_the_document(api: str, db: Database[dict[str, Any]]) -> None:
    response = create(api, ALICE)

    assert response.status_code == 201
    contact_id = response.json()["id"]
    stored = db.contacts.find_one({"_id": ObjectId(contact_id)})
    assert stored is not None
    assert {key: stored[key] for key in ("owner", "name", "email")} == ALICE
    # Stored as a BSON date, not a string: TTL indexes and date queries depend on that.
    assert isinstance(stored["created_at"], datetime)


def test_read_returns_what_was_stored(api: str) -> None:
    contact_id = create(api, ALICE).json()["id"]

    response = requests.get(f"{api}/contacts/{contact_id}", timeout=10)

    assert response.status_code == 200
    assert response.json() == {"id": contact_id, **ALICE}


def test_update_changes_only_the_named_field(api: str, db: Database[dict[str, Any]]) -> None:
    contact_id = create(api, ALICE).json()["id"]
    before = db.contacts.find_one({"_id": ObjectId(contact_id)})

    response = requests.patch(f"{api}/contacts/{contact_id}", json={"name": "Ana L."}, timeout=10)

    assert response.status_code == 200
    after = db.contacts.find_one({"_id": ObjectId(contact_id)})
    assert before is not None
    assert after == before | {"name": "Ana L."}  # $set touched one field, nothing else


def test_delete_removes_the_document(api: str, db: Database[dict[str, Any]]) -> None:
    contact_id = create(api, ALICE).json()["id"]

    assert requests.delete(f"{api}/contacts/{contact_id}", timeout=10).status_code == 204

    assert db.contacts.count_documents({}) == 0
    assert requests.get(f"{api}/contacts/{contact_id}", timeout=10).status_code == 404


def test_malformed_id_is_404_not_500(api: str) -> None:
    assert requests.get(f"{api}/contacts/not-an-object-id", timeout=10).status_code == 404
