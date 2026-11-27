"""Session expiry with a TTL index, tested without waiting an hour.

A TTL index deletes a document some time after its date field, in a background job that
runs about once a minute. So tests can't wait for "exactly an hour later". Instead:

1. Check the index definition (the field, the number of seconds).
2. Check the app's own expiry logic with an injected clock: TTL deletion is late by
   design, so the app must treat an old session as expired even while it still exists.
3. One test does watch the server delete a document, with the TTL monitor sped up to
   run every second (see conftest.py). That wait is inherent, so it polls with a timeout.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests
from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database

from common.http_server import serve
from common.polling import wait_until
from mongodb.app.api import create_app
from mongodb.app.collections import SESSION_TTL_SECONDS


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@pytest.fixture
def clock() -> FakeClock:
    # Starts at the real current time, so the server's TTL monitor won't delete the
    # session during the test: only the app's clock moves forward.
    return FakeClock(datetime.now(UTC))


@pytest.fixture
def api_with_clock(
    mongo_client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]], clock: FakeClock
) -> Iterator[str]:
    with serve(create_app(mongo_client, db, clock=clock)) as base_url:
        yield base_url


def test_ttl_index_definition(db: Database[dict[str, Any]]) -> None:
    index = db.sessions.index_information()["session_ttl"]
    assert index["key"] == [("created_at", 1)]
    assert index["expireAfterSeconds"] == SESSION_TTL_SECONDS == 3600


def test_session_is_valid_until_the_ttl(api_with_clock: str, db: Database[dict[str, Any]], clock: FakeClock) -> None:
    token = requests.post(f"{api_with_clock}/sessions", params={"owner": "alice"}, timeout=10).json()["token"]

    clock.advance(minutes=59)
    assert requests.get(f"{api_with_clock}/sessions/{token}", timeout=10).status_code == 200

    clock.advance(minutes=2)  # 61 minutes old
    assert requests.get(f"{api_with_clock}/sessions/{token}", timeout=10).status_code == 401
    # The document is still there: the TTL monitor hasn't (and needn't have) run yet.
    # Without the app's own age check, this expired session would still be accepted.
    assert db.sessions.find_one({"_id": ObjectId(token)}) is not None


def test_server_deletes_an_expired_document(db: Database[dict[str, Any]]) -> None:
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    session_id = db.sessions.insert_one({"owner": "alice", "created_at": two_hours_ago}).inserted_id

    wait_until(
        lambda: db.sessions.find_one({"_id": session_id}) is None,
        timeout=30,
        interval=0.5,
        description="the TTL monitor to delete the expired session",
    )
