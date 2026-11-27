"""A small contacts API on MongoDB. Tests call it over HTTP and inspect the collections."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, WriteError

from mongodb.app.collections import SESSION_TTL_SECONDS, Document

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


class ContactIn(BaseModel):
    owner: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=100)
    # No format check here on purpose: the collection's $jsonSchema validator owns that
    # rule, and the API turns its rejection into a 422.
    email: str


class ContactPatch(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ContactWithMessageIn(ContactIn):
    first_message: str


def object_id(raw: str) -> ObjectId:
    try:
        return ObjectId(raw)
    except InvalidId as error:
        raise HTTPException(status_code=404, detail="Not found") from error


def to_json(doc: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(doc["_id"]), "owner": doc["owner"], "name": doc["name"], "email": doc["email"]}


def create_app(client: MongoClient[Document], db: Database[Document], clock: Clock = utc_now) -> FastAPI:
    """`clock` is injectable so tests can decide what "now" is (see the TTL tests)."""
    app = FastAPI(title="contacts-mongo")

    @app.post("/contacts", status_code=201)
    def create_contact(body: ContactIn) -> dict[str, Any]:
        doc = body.model_dump() | {"created_at": clock()}
        try:
            result = db.contacts.insert_one(doc)
        except DuplicateKeyError as error:  # the unique index on email
            raise HTTPException(status_code=409, detail="Email already used") from error
        except WriteError as error:  # the $jsonSchema validator (error code 121)
            raise HTTPException(status_code=422, detail="Rejected by the database") from error
        return to_json(doc | {"_id": result.inserted_id})

    @app.get("/contacts/{contact_id}")
    def get_contact(contact_id: str) -> dict[str, Any]:
        doc = db.contacts.find_one({"_id": object_id(contact_id)})
        if doc is None:
            raise HTTPException(status_code=404, detail="Not found")
        return to_json(doc)

    @app.patch("/contacts/{contact_id}")
    def rename_contact(contact_id: str, body: ContactPatch) -> dict[str, Any]:
        result = db.contacts.update_one({"_id": object_id(contact_id)}, {"$set": {"name": body.name}})
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Not found")
        return get_contact(contact_id)

    @app.delete("/contacts/{contact_id}", status_code=204)
    def delete_contact(contact_id: str) -> None:
        if db.contacts.delete_one({"_id": object_id(contact_id)}).deleted_count == 0:
            raise HTTPException(status_code=404, detail="Not found")

    @app.post("/contacts-with-message", status_code=201)
    def create_contact_with_message(body: ContactWithMessageIn) -> dict[str, Any]:
        """Two inserts that must succeed or fail together: a multi-document transaction."""
        now = clock()
        contact = {"owner": body.owner, "name": body.name, "email": body.email, "created_at": now}
        try:
            with client.start_session() as session, session.start_transaction():
                contact_id = db.contacts.insert_one(contact, session=session).inserted_id
                db.messages.insert_one(
                    {"contact_id": contact_id, "owner": body.owner, "body": body.first_message, "sent_at": now},
                    session=session,
                )
        except WriteError as error:
            # Leaving the `with` block on an exception aborts the transaction: the contact
            # insert above is undone too.
            raise HTTPException(status_code=422, detail="Rejected by the database") from error
        return to_json(contact | {"_id": contact_id})

    @app.post("/sessions", status_code=201)
    def open_session(owner: str) -> dict[str, str]:
        result = db.sessions.insert_one({"owner": owner, "created_at": clock()})
        return {"token": str(result.inserted_id)}

    @app.get("/sessions/{token}")
    def check_session(token: str) -> dict[str, str]:
        # TTL deletion is lazy: the monitor runs about once a minute, and may lag further
        # under load. An expired session can still be in the collection, so the read
        # must check the age itself instead of trusting "it exists, so it's valid".
        cutoff = clock() - timedelta(seconds=SESSION_TTL_SECONDS)
        doc = db.sessions.find_one({"_id": object_id(token), "created_at": {"$gt": cutoff}})
        if doc is None:
            raise HTTPException(status_code=401, detail="Session expired or unknown")
        return {"owner": doc["owner"]}

    return app
