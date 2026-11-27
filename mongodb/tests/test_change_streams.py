"""Change streams: an API write produces the expected event for subscribers."""

from collections.abc import Iterator
from typing import Any

import pytest
import requests
from bson import ObjectId
from pymongo.change_stream import ChangeStream
from pymongo.database import Database

from common.polling import wait_until

Stream = ChangeStream[dict[str, Any]]


@pytest.fixture
def contact_changes(db: Database[dict[str, Any]]) -> Iterator[Stream]:
    # Opened BEFORE the write: a change stream only sees changes made after it opens.
    with db.contacts.watch(max_await_time_ms=500) as stream:
        yield stream


def next_change(stream: Stream) -> dict[str, Any]:
    # try_next() waits up to max_await_time_ms on the server, then returns None if there
    # is nothing yet. Delivery is asynchronous, so poll with an overall timeout.
    change: dict[str, Any] = wait_until(stream.try_next, timeout=10, interval=0, description="a change event")
    return change


def test_create_emits_an_insert_event(api: str, contact_changes: Stream) -> None:
    contact_id = requests.post(
        f"{api}/contacts", json={"owner": "alice", "name": "Ana", "email": "ana@example.com"}, timeout=10
    ).json()["id"]

    change = next_change(contact_changes)

    assert change["operationType"] == "insert"
    assert change["documentKey"] == {"_id": ObjectId(contact_id)}
    assert change["fullDocument"]["email"] == "ana@example.com"


def test_rename_emits_an_update_with_only_the_changed_field(
    api: str, db: Database[dict[str, Any]], contact_changes: Stream
) -> None:
    contact_id = requests.post(
        f"{api}/contacts", json={"owner": "alice", "name": "Ana", "email": "ana@example.com"}, timeout=10
    ).json()["id"]
    assert next_change(contact_changes)["operationType"] == "insert"

    requests.patch(f"{api}/contacts/{contact_id}", json={"name": "Ana Lima"}, timeout=10)
    change = next_change(contact_changes)

    assert change["operationType"] == "update"
    assert change["documentKey"] == {"_id": ObjectId(contact_id)}
    assert change["updateDescription"]["updatedFields"] == {"name": "Ana Lima"}
    assert change["updateDescription"]["removedFields"] == []
