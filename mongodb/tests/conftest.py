"""A real MongoDB, started once per session as a single-node replica set.

A replica set (even of one node) is what enables multi-document transactions and
change streams; a standalone mongod supports neither.
"""

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import allure
import pytest
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import PyMongoError
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from common.http_server import serve
from common.polling import wait_until
from mongodb.app.api import create_app
from mongodb.app.collections import ensure_collections

MONGO_IMAGE = "mongo:8.0.38"


@pytest.fixture(autouse=True)
def _allure_labels() -> None:
    allure.dynamic.parent_suite("MongoDB")


@pytest.fixture(scope="session")
def mongo_client() -> Iterator[MongoClient[dict[str, Any]]]:
    container = (
        DockerContainer(MONGO_IMAGE)
        # ttlMonitorSleepSecs=1: the TTL monitor runs every second instead of every 60,
        # so the one test that watches a real TTL deletion finishes quickly.
        .with_command("--replSet rs0 --bind_ip_all --setParameter ttlMonitorSleepSecs=1")
        .with_exposed_ports(27017)
        .waiting_for(LogMessageWaitStrategy("Waiting for connections"))
    )
    with container:
        host, port = container.get_container_host_ip(), int(container.get_exposed_port(27017))
        # Talk to this one node directly: the replica set's member address
        # (localhost:27017 inside the container) isn't reachable from the host.
        bootstrap: MongoClient[dict[str, Any]] = MongoClient(host, port, directConnection=True)
        with bootstrap:
            bootstrap.admin.command(
                "replSetInitiate", {"_id": "rs0", "members": [{"_id": 0, "host": "localhost:27017"}]}
            )
            # Electing itself primary takes a moment; that wait is inherent, so poll.
            wait_until(
                lambda: bootstrap.admin.command("hello").get("isWritablePrimary"),
                timeout=60,
                description="the replica set to elect a primary",
                ignore=(PyMongoError,),
            )
        # A new client: the bootstrap one first saw a standalone server, and decided
        # sessions (and so transactions) weren't supported.
        client: MongoClient[dict[str, Any]] = MongoClient(host, port, directConnection=True, tz_aware=True)
        yield client
        client.close()


@pytest.fixture
def db(mongo_client: MongoClient[dict[str, Any]]) -> Iterator[Database[dict[str, Any]]]:
    """A fresh database per test: no shared documents, safe to run in parallel."""
    name = f"test_{uuid4().hex[:12]}"
    database = mongo_client[name]
    ensure_collections(database)
    yield database
    mongo_client.drop_database(name)


@pytest.fixture
def api(mongo_client: MongoClient[dict[str, Any]], db: Database[dict[str, Any]]) -> Iterator[str]:
    with serve(create_app(mongo_client, db)) as base_url:
        yield base_url
