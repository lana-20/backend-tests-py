"""An aggregation pipeline, checked against hand-computed results."""

from datetime import UTC, datetime
from typing import Any

from pymongo.database import Database

from mongodb.app.reports import message_stats


def day(n: int) -> datetime:
    return datetime(2026, 3, n, 12, 0, tzinfo=UTC)


def test_message_stats_per_contact(db: Database[dict[str, Any]]) -> None:
    ana, ben = db.contacts.insert_many(
        [
            {"owner": "alice", "name": "Ana", "email": "ana@example.com", "created_at": day(1)},
            {"owner": "alice", "name": "Ben", "email": "ben@example.com", "created_at": day(1)},
        ]
    ).inserted_ids
    bobs_contact = db.contacts.insert_one(
        {"owner": "bob", "name": "Cy", "email": "cy@example.com", "created_at": day(1)}
    ).inserted_id
    db.messages.insert_many(
        [
            {"contact_id": ana, "owner": "alice", "body": "hi", "sent_at": day(2)},
            {"contact_id": ana, "owner": "alice", "body": "again", "sent_at": day(5)},
            {"contact_id": ben, "owner": "alice", "body": "hello", "sent_at": day(3)},
            {"contact_id": ana, "owner": "alice", "body": "third", "sent_at": day(4)},
            {"contact_id": bobs_contact, "owner": "bob", "body": "not alice's", "sent_at": day(9)},
        ]
    )

    assert message_stats(db, "alice") == [
        {"contact": "Ana", "messages": 3, "last_sent_at": day(5)},
        {"contact": "Ben", "messages": 1, "last_sent_at": day(3)},
    ]


def test_message_stats_for_an_owner_with_no_messages(db: Database[dict[str, Any]]) -> None:
    assert message_stats(db, "nobody") == []
