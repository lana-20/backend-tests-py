"""Contacts in Firestore: documents, a composite query, and a transaction."""

from typing import Any

from google.cloud import firestore


def add_contact(db: firestore.Client, contact_id: str, owner: str, name: str, tags: list[str]) -> None:
    # create() fails if the document exists; set() would silently overwrite it.
    db.collection("contacts").document(contact_id).create(
        {"owner": owner, "name": name, "tags": tags, "message_count": 0}
    )


def contacts_with_tag(db: firestore.Client, owner: str, tag: str) -> list[str]:
    """A composite query: equality + array-contains + order by another field.

    Production Firestore rejects this until the composite index in
    firestore.indexes.json is deployed. The emulator doesn't require indexes at all,
    so this repo keeps the index file next to the query, and the README says so.
    """
    query = (
        db.collection("contacts")
        .where(filter=firestore.FieldFilter("owner", "==", owner))
        .where(filter=firestore.FieldFilter("tags", "array_contains", tag))
        .order_by("name")
    )
    return [snapshot.id for snapshot in query.stream()]


def record_message(db: firestore.Client, contact_id: str, body: str, *, fail_after_writes: bool = False) -> None:
    """Add a message and bump the contact's counter, atomically.

    `fail_after_writes` exists only so a test can prove that a failure inside the
    transaction leaves no partial write behind.
    """
    contact_ref = db.collection("contacts").document(contact_id)
    message_ref = contact_ref.collection("messages").document()

    @firestore.transactional
    def run(transaction: firestore.Transaction) -> None:
        # Reads must come before writes in a Firestore transaction. If another client
        # changes the contact before we commit, Firestore retries this function.
        snapshot: Any = contact_ref.get(transaction=transaction)
        count = snapshot.get("message_count")
        transaction.update(contact_ref, {"message_count": count + 1})
        transaction.set(message_ref, {"body": body})
        if fail_after_writes:
            raise RuntimeError("simulated failure before commit")

    run(db.transaction())
