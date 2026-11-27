"""Cache-aside (lazy loading) in front of a slower source of truth.

Read:  look in Redis; on a miss, load from the source and store it with a TTL.
Write: update the source, then DELETE the cached copy (don't overwrite it). The next
       read reloads it. Deleting is safer than writing the new value into the cache:
       two concurrent writers can't leave the older value in the cache last.
The TTL is the safety net: even if an invalidation is missed, stale data ages out.
"""

import json
from dataclasses import asdict, dataclass

import redis


@dataclass
class Contact:
    id: int
    name: str
    email: str


class ContactSource:
    """Stands in for the real database. Counts reads, so tests can see cache misses."""

    def __init__(self, contacts: list[Contact]) -> None:
        self._rows = {contact.id: contact for contact in contacts}
        self.reads = 0

    def get(self, contact_id: int) -> Contact | None:
        self.reads += 1
        return self._rows.get(contact_id)

    def rename(self, contact_id: int, name: str) -> Contact | None:
        contact = self._rows.get(contact_id)
        if contact is not None:
            contact.name = name
        return contact


class ContactCache:
    def __init__(self, client: redis.Redis, source: ContactSource, *, ttl_seconds: int, key_prefix: str = "") -> None:
        self.client = client
        self.source = source
        self.ttl_seconds = ttl_seconds
        # A prefix per app (and per test) keeps keys from colliding in a shared Redis.
        self.key_prefix = key_prefix

    def key(self, contact_id: int) -> str:
        return f"{self.key_prefix}contact:{contact_id}"

    def get(self, contact_id: int) -> tuple[Contact | None, bool]:
        """Return (contact, cache_hit)."""
        cached = self.client.get(self.key(contact_id))
        if cached is not None:
            return Contact(**json.loads(cached)), True

        contact = self.source.get(contact_id)
        if contact is not None:
            self.client.set(self.key(contact_id), json.dumps(asdict(contact)), ex=self.ttl_seconds)
        return contact, False

    def rename(self, contact_id: int, name: str) -> Contact | None:
        contact = self.source.rename(contact_id, name)  # 1. write the source of truth
        self.client.delete(self.key(contact_id))  # 2. then invalidate
        return contact
