"""Collection setup: validators and indexes are part of the schema, so they live in code.

MongoDB is schemaless by default. A $jsonSchema validator makes the server itself reject
malformed documents, even ones written by another service or a manual shell session.
"""

from typing import Any

from pymongo import ASCENDING, DESCENDING
from pymongo.database import Database

# PyMongo is generic over the document type; we use plain dicts.
Document = dict[str, Any]

SESSION_TTL_SECONDS = 3600

CONTACT_SCHEMA = {
    "bsonType": "object",
    "required": ["owner", "name", "email", "created_at"],
    "properties": {
        "owner": {"bsonType": "string", "minLength": 1},
        "name": {"bsonType": "string", "minLength": 1, "maxLength": 100},
        "email": {"bsonType": "string", "pattern": "^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$"},
        "created_at": {"bsonType": "date"},
    },
}

MESSAGE_SCHEMA = {
    "bsonType": "object",
    "required": ["contact_id", "owner", "body", "sent_at"],
    "properties": {
        "contact_id": {"bsonType": "objectId"},
        "owner": {"bsonType": "string"},
        "body": {"bsonType": "string", "minLength": 1},
        "sent_at": {"bsonType": "date"},
    },
}


def ensure_collections(db: Database[Document]) -> None:
    db.create_collection("contacts", validator={"$jsonSchema": CONTACT_SCHEMA})
    db.contacts.create_index([("email", ASCENDING)], unique=True, name="email_unique")
    # Serves "this owner's contacts, newest first" without an in-memory sort.
    db.contacts.create_index([("owner", ASCENDING), ("created_at", DESCENDING)], name="owner_created_at")

    db.create_collection("messages", validator={"$jsonSchema": MESSAGE_SCHEMA})
    db.messages.create_index([("owner", ASCENDING), ("contact_id", ASCENDING)], name="owner_contact")

    # TTL index: a background monitor deletes a session about an hour after created_at.
    db.create_collection("sessions")
    db.sessions.create_index("created_at", expireAfterSeconds=SESSION_TTL_SECONDS, name="session_ttl")
