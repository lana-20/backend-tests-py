from collections.abc import Iterator
from dataclasses import dataclass
from uuid import uuid4

import allure
import pytest
import redis
from testcontainers.community.redis import RedisContainer

from common.http_server import serve
from redis_cache.app.api import create_app
from redis_cache.app.cache import Contact, ContactCache, ContactSource

REDIS_IMAGE = "redis:8.4.8"
TTL_SECONDS = 300


@pytest.fixture(autouse=True)
def _allure_labels() -> None:
    allure.dynamic.parent_suite("Redis")


@pytest.fixture(scope="session")
def redis_client() -> Iterator[redis.Redis]:
    with RedisContainer(REDIS_IMAGE) as container:  # waits until PING answers
        client = container.get_client(decode_responses=True)
        yield client
        client.close()


@dataclass
class CacheUnderTest:
    base_url: str
    cache: ContactCache
    source: ContactSource


@pytest.fixture
def app(redis_client: redis.Redis) -> Iterator[CacheUnderTest]:
    source = ContactSource([Contact(1, "Ana", "ana@example.com"), Contact(2, "Ben", "ben@example.com")])
    # A unique key prefix per test: tests share one Redis but never each other's keys.
    cache = ContactCache(redis_client, source, ttl_seconds=TTL_SECONDS, key_prefix=f"test:{uuid4().hex[:8]}:")
    with serve(create_app(cache)) as base_url:
        yield CacheUnderTest(base_url, cache, source)
