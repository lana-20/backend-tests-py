"""HTTP API over the cache. X-Cache: HIT or MISS makes cache behavior visible."""

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

from redis_cache.app.cache import ContactCache


class Rename(BaseModel):
    name: str = Field(min_length=1)


def create_app(cache: ContactCache) -> FastAPI:
    app = FastAPI(title="contacts-cache")

    @app.get("/contacts/{contact_id}")
    def get_contact(contact_id: int, response: Response) -> dict[str, Any]:
        contact, hit = cache.get(contact_id)
        if contact is None:
            raise HTTPException(status_code=404, detail="Not found")
        response.headers["X-Cache"] = "HIT" if hit else "MISS"
        return asdict(contact)

    @app.put("/contacts/{contact_id}")
    def rename_contact(contact_id: int, body: Rename) -> dict[str, Any]:
        contact = cache.rename(contact_id, body.name)
        if contact is None:
            raise HTTPException(status_code=404, detail="Not found")
        return asdict(contact)

    return app
