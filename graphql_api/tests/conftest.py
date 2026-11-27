from collections.abc import Iterator

import allure
import pytest
from sqlalchemy import Engine

from common.http_server import serve
from graphql_api.app.db import make_engine, seed
from graphql_api.app.server import create_app
from graphql_api.tests.client import GraphQLClient

# alice owns contacts 1-3, bob owns 4-5. Two messages each.
SEED = {"alice": 3, "bob": 2}


@pytest.fixture(autouse=True)
def _allure_labels() -> None:
    allure.dynamic.parent_suite("GraphQL")


@pytest.fixture
def engine() -> Iterator[Engine]:
    """A fresh in-memory database per test, so tests never share state."""
    engine = make_engine()
    seed(engine, SEED)
    yield engine
    engine.dispose()


@pytest.fixture
def api(engine: Engine) -> Iterator[GraphQLClient]:
    """The real app, served by uvicorn on a free port, called over HTTP."""
    with serve(create_app(engine)) as base_url:
        yield GraphQLClient(f"{base_url}/graphql")
