"""N+1 detection: count the SQL statements one GraphQL request causes.

A list of N contacts, each with a nested `messages` field, naively costs 1 query for the
list plus 1 per contact. A DataLoader collects the contact ids first and loads all
their messages in one query. The test pins the query count, so a regression (someone
bypasses the loader) fails CI instead of slowing production down.
"""

import pytest
from sqlalchemy import Engine

from common.http_server import serve
from graphql_api.app.db import make_engine, seed
from graphql_api.app.server import create_app
from graphql_api.tests.client import GraphQLClient
from graphql_api.tests.query_counter import count_queries

QUERY = "query { contacts(first: 50) { edges { node { name messages { body } } } } }"


def queries_for_contacts(contact_count: int, *, use_dataloader: bool) -> int:
    """Seed `contact_count` contacts, run QUERY once, return how many SQL statements ran."""
    engine: Engine = make_engine()
    seed(engine, {"alice": contact_count})
    try:
        with serve(create_app(engine, use_dataloader=use_dataloader)) as base_url:
            api = GraphQLClient(f"{base_url}/graphql")
            with count_queries(engine) as statements:
                response = api.execute(QUERY, token="alice-token")
        assert response.errors == []
        assert len(response.data["contacts"]["edges"]) == contact_count
        return len(statements)
    finally:
        engine.dispose()


@pytest.mark.parametrize("contact_count", [1, 5, 20])
def test_with_dataloader_the_query_count_is_constant(contact_count: int) -> None:
    # 1 for the page of contacts + 1 for all of their messages, however many contacts.
    assert queries_for_contacts(contact_count, use_dataloader=True) == 2


@pytest.mark.parametrize("contact_count", [1, 5, 20])
def test_without_dataloader_the_counter_catches_n_plus_one(contact_count: int) -> None:
    # Proves the check can fail: the naive resolver costs 1 + N queries.
    assert queries_for_contacts(contact_count, use_dataloader=False) == 1 + contact_count
