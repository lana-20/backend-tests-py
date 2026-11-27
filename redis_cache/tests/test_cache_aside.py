"""Cache-aside: misses fill the cache, hits skip the source, writes invalidate."""

import json

import redis
import requests

from common.polling import wait_until
from redis_cache.tests.conftest import TTL_SECONDS, CacheUnderTest


def get(app: CacheUnderTest, contact_id: int) -> requests.Response:
    return requests.get(f"{app.base_url}/contacts/{contact_id}", timeout=10)


def test_first_read_misses_and_fills_the_cache(app: CacheUnderTest, redis_client: redis.Redis) -> None:
    response = get(app, 1)

    assert response.headers["X-Cache"] == "MISS"
    assert app.source.reads == 1
    stored = redis_client.get(app.cache.key(1))
    assert stored is not None
    assert json.loads(stored) == {"id": 1, "name": "Ana", "email": "ana@example.com"}


def test_second_read_is_served_from_the_cache(app: CacheUnderTest) -> None:
    get(app, 1)
    response = get(app, 1)

    assert response.headers["X-Cache"] == "HIT"
    assert response.json()["name"] == "Ana"
    assert app.source.reads == 1  # the source was not asked again


def test_cached_entries_have_a_ttl(app: CacheUnderTest, redis_client: redis.Redis) -> None:
    get(app, 1)

    # TTL returns -1 for a key without expiry, and -2 for a missing key. A cache entry
    # without a TTL would live forever if an invalidation were ever missed.
    ttl = redis_client.ttl(app.cache.key(1))
    assert 0 < ttl <= TTL_SECONDS


def test_update_invalidates_the_cached_copy(app: CacheUnderTest, redis_client: redis.Redis) -> None:
    get(app, 1)  # cached as "Ana"

    response = requests.put(f"{app.base_url}/contacts/1", json={"name": "Ana Lima"}, timeout=10)

    assert response.status_code == 200
    assert redis_client.exists(app.cache.key(1)) == 0
    reread = get(app, 1)
    assert reread.headers["X-Cache"] == "MISS"
    assert reread.json()["name"] == "Ana Lima"  # not the stale "Ana"
    assert app.source.reads == 2


def test_update_of_an_uncached_contact_does_not_create_a_key(app: CacheUnderTest, redis_client: redis.Redis) -> None:
    requests.put(f"{app.base_url}/contacts/2", json={"name": "Benjamin"}, timeout=10)
    assert redis_client.exists(app.cache.key(2)) == 0


def test_expired_entry_is_reloaded_from_the_source(app: CacheUnderTest, redis_client: redis.Redis) -> None:
    get(app, 1)
    # Rather than wait 300 s, shorten this key's TTL to 1 ms. Redis then treats it as
    # gone on the next access. Polling covers the millisecond.
    redis_client.pexpire(app.cache.key(1), 1)
    wait_until(lambda: redis_client.exists(app.cache.key(1)) == 0, timeout=5, interval=0.01, description="expiry")

    response = get(app, 1)

    assert response.headers["X-Cache"] == "MISS"
    assert app.source.reads == 2


def test_missing_contact_is_404_and_not_cached(app: CacheUnderTest, redis_client: redis.Redis) -> None:
    assert get(app, 999).status_code == 404
    assert redis_client.exists(app.cache.key(999)) == 0
