"""A multi-document transaction: a contact and its first message, all or nothing."""

from typing import Any

import requests
from pymongo.database import Database

BODY = {"owner": "alice", "name": "Ana", "email": "ana@example.com"}


def test_both_documents_are_written_together(api: str, db: Database[dict[str, Any]]) -> None:
    response = requests.post(f"{api}/contacts-with-message", json=BODY | {"first_message": "Welcome!"}, timeout=10)

    assert response.status_code == 201
    contact = db.contacts.find_one({"email": "ana@example.com"})
    assert contact is not None
    assert db.messages.find_one({"contact_id": contact["_id"]}, {"_id": 0, "body": 1}) == {"body": "Welcome!"}


def test_a_failed_second_write_rolls_back_the_first(api: str, db: Database[dict[str, Any]]) -> None:
    # The contact insert succeeds, then the message insert is rejected by the messages
    # validator (empty body). The transaction must undo the contact too.
    response = requests.post(f"{api}/contacts-with-message", json=BODY | {"first_message": ""}, timeout=10)

    assert response.status_code == 422
    assert db.contacts.count_documents({}) == 0
    assert db.messages.count_documents({}) == 0
