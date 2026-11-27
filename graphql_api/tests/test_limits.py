"""Abusive queries are rejected before any resolver (or database query) runs.

One GraphQL request can ask for an enormous amount of work. The schema here has a cycle
(contact -> messages -> contact -> ...), so without limits a client could nest it as
deep as it likes. The limits are checked during validation, so the test also proves
that the database was never touched.
"""

from sqlalchemy import Engine

from graphql_api.app.schema import MAX_ALIASES, MAX_DEPTH
from graphql_api.tests.client import GraphQLClient
from graphql_api.tests.query_counter import count_queries


def nested_query(depth: int) -> str:
    """contact { messages { contact { messages { ... { id } } } } } at the given depth."""
    fields = ["contact", "messages"]  # odd levels are messages, even levels contact
    inner = "id"
    for level in range(depth - 1, 0, -1):
        inner = f"{fields[level % 2]} {{ {inner} }}"
    return f'query {{ contact(id: "1") {{ {inner} }} }}'


def test_query_at_the_depth_limit_is_allowed(api: GraphQLClient) -> None:
    response = api.execute(nested_query(MAX_DEPTH), token="alice-token")
    assert response.errors == []
    assert response.data["contact"] is not None


def test_query_past_the_depth_limit_is_rejected_without_running(api: GraphQLClient, engine: Engine) -> None:
    with count_queries(engine) as statements:
        response = api.execute(nested_query(MAX_DEPTH + 4), token="alice-token")

    assert response.status == 200
    assert response.data is None
    assert f"exceeds maximum operation depth of {MAX_DEPTH}" in response.errors[0]["message"]
    assert statements == []


def test_too_many_aliases_are_rejected_without_running(api: GraphQLClient, engine: Engine) -> None:
    # The same cheap field 100 times under different names: 100x the work, one request.
    aliases = " ".join(f'c{n}: contact(id: "1") {{ name }}' for n in range(100))
    with count_queries(engine) as statements:
        response = api.execute(f"query {{ {aliases} }}", token="alice-token")

    assert response.data is None
    assert f"Allowed: {MAX_ALIASES}" in response.errors[0]["message"]
    assert statements == []


def test_oversized_documents_are_rejected(api: GraphQLClient) -> None:
    fields = " ".join(["id name owner"] * 1000)
    response = api.execute(f'query {{ contact(id: "1") {{ {fields} }} }}', token="alice-token")

    assert response.data is None
    assert "token" in response.errors[0]["message"].lower()
