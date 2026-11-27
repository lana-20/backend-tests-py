"""Firestore emulator: CRUD, a composite query, a transaction, and security rules."""

from pathlib import Path

import pytest
from google.api_core.exceptions import AlreadyExists
from google.cloud import firestore

from document_stores.firestore.contacts import add_contact, contacts_with_tag, record_message
from document_stores.firestore.rest_client import EmulatorRestClient

RULES = (Path(__file__).resolve().parent.parent / "firestore.rules").read_text()


# --- Documents -------------------------------------------------------------------------


def test_document_round_trip(db: firestore.Client) -> None:
    add_contact(db, "ana", owner="alice", name="Ana", tags=["work"])

    snapshot = db.collection("contacts").document("ana").get()

    assert snapshot.exists
    assert snapshot.to_dict() == {"owner": "alice", "name": "Ana", "tags": ["work"], "message_count": 0}


def test_create_refuses_to_overwrite(db: firestore.Client) -> None:
    add_contact(db, "ana", owner="alice", name="Ana", tags=[])
    with pytest.raises(AlreadyExists):
        add_contact(db, "ana", owner="alice", name="Someone else", tags=[])


def test_update_and_delete(db: firestore.Client) -> None:
    add_contact(db, "ana", owner="alice", name="Ana", tags=[])
    ref = db.collection("contacts").document("ana")

    ref.update({"name": "Ana Lima"})
    assert ref.get().get("name") == "Ana Lima"

    ref.delete()
    assert not ref.get().exists


# --- Composite query -------------------------------------------------------------------


def test_composite_query(db: firestore.Client) -> None:
    add_contact(db, "c1", owner="alice", name="Zed", tags=["work", "vip"])
    add_contact(db, "c2", owner="alice", name="Ana", tags=["work"])
    add_contact(db, "c3", owner="alice", name="Moe", tags=["family"])
    add_contact(db, "c4", owner="bob", name="Bea", tags=["work"])

    # alice's contacts tagged "work", ordered by name: c2 (Ana) before c1 (Zed).
    assert contacts_with_tag(db, owner="alice", tag="work") == ["c2", "c1"]


# --- Transaction -----------------------------------------------------------------------


def test_transaction_writes_message_and_counter_together(db: firestore.Client) -> None:
    add_contact(db, "ana", owner="alice", name="Ana", tags=[])

    record_message(db, "ana", "Hello")
    record_message(db, "ana", "Again")

    contact = db.collection("contacts").document("ana")
    assert contact.get().get("message_count") == 2
    assert sorted(m.get("body") for m in contact.collection("messages").stream()) == ["Again", "Hello"]


def test_failed_transaction_leaves_nothing_behind(db: firestore.Client) -> None:
    add_contact(db, "ana", owner="alice", name="Ana", tags=[])

    with pytest.raises(RuntimeError, match="simulated failure"):
        record_message(db, "ana", "Lost", fail_after_writes=True)

    contact = db.collection("contacts").document("ana")
    assert contact.get().get("message_count") == 0
    assert list(contact.collection("messages").stream()) == []


# --- Security rules (through the REST API, as end users) -------------------------------


@pytest.fixture
def ruled(db: firestore.Client, rest: EmulatorRestClient) -> EmulatorRestClient:
    rest.load_rules(RULES)
    add_contact(db, "ana", owner="alice", name="Ana", tags=[])  # admin SDK: rules don't apply
    return rest


def test_owner_can_read_their_contact(ruled: EmulatorRestClient) -> None:
    response = ruled.get("contacts/ana", uid="alice")
    assert response.status_code == 200
    assert response.json()["fields"]["name"] == {"stringValue": "Ana"}


@pytest.mark.parametrize("uid", ["bob", None], ids=["another user", "signed out"])
def test_others_cannot_read_it(ruled: EmulatorRestClient, uid: str | None) -> None:
    response = ruled.get("contacts/ana", uid=uid)
    assert response.status_code == 403
    assert response.json()["error"]["status"] == "PERMISSION_DENIED"


def test_users_can_create_only_their_own_contacts(ruled: EmulatorRestClient) -> None:
    mine = ruled.create("contacts", "bea", {"owner": "bob", "name": "Bea"}, uid="bob")
    assert mine.status_code == 200

    forged = ruled.create("contacts", "eve", {"owner": "alice", "name": "Planted"}, uid="bob")
    assert forged.status_code == 403
