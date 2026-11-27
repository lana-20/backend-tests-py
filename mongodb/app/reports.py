"""An aggregation pipeline: per-contact message counts for one owner."""

from typing import Any

from pymongo.database import Database

from mongodb.app.collections import Document


def message_stats(db: Database[Document], owner: str) -> list[dict[str, Any]]:
    pipeline: list[dict[str, Any]] = [
        {"$match": {"owner": owner}},  # first, so it can use the owner_contact index
        {"$group": {"_id": "$contact_id", "messages": {"$sum": 1}, "last_sent_at": {"$max": "$sent_at"}}},
        {"$lookup": {"from": "contacts", "localField": "_id", "foreignField": "_id", "as": "contact"}},
        {"$unwind": "$contact"},
        {"$project": {"_id": 0, "contact": "$contact.name", "messages": 1, "last_sent_at": 1}},
        {"$sort": {"messages": -1, "contact": 1}},
    ]
    return list(db.messages.aggregate(pipeline))
