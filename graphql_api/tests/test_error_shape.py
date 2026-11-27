"""How GraphQL reports problems, compared with a REST API.

REST picks a status code per request. GraphQL serves one endpoint, usually answers
200, and reports problems in an `errors` array, next to whatever `data` it could
produce. So tests must check the body, never just the status.

Request errors (bad syntax, unknown fields, bad variables) mean nothing executed.
The spec says to leave `data` out then; Strawberry sends `"data": null`. Clients
should treat both the same, and these tests check `data is None`, which covers both.
"""

from graphql_api.tests.client import GraphQLClient


def test_errors_and_data_side_by_side_in_one_response(api: GraphQLClient) -> None:
    # Aliases ask for the same field twice; only the second needs a permission bob lacks.
    query = """
    query {
      allowed: contact(id: "1") { name }
      denied: contact(id: "1") { email }
    }
    """
    response = api.execute(query, token="bob-token")

    assert response.status == 200
    assert response.data == {"allowed": {"name": "Alice contact 1"}, "denied": {"email": None}}
    assert [error["path"] for error in response.errors] == [["denied", "email"]]


def test_syntax_error_has_a_location_and_no_data(api: GraphQLClient) -> None:
    response = api.execute("query { contacts { edges { node { id }", token="alice-token")

    assert response.status == 200
    assert response.data is None  # never executed
    error = response.errors[0]
    assert error["message"].startswith("Syntax Error")
    assert error["locations"] == [{"line": 1, "column": 39}]


def test_unknown_field_fails_validation(api: GraphQLClient) -> None:
    response = api.execute('query { contact(id: "1") { phone } }', token="alice-token")

    assert response.data is None
    assert response.errors[0]["message"] == "Cannot query field 'phone' on type 'Contact'."


def test_error_messages_do_not_leak_internals(api: GraphQLClient) -> None:
    # A malformed cursor makes base64 decoding fail inside the resolver. The client should
    # get a clean, coded error, not a Python exception message.
    response = api.execute('query { contacts(after: "%%%") { edges { cursor } } }', token="alice-token")

    assert response.error_codes == ["BAD_USER_INPUT"]
    assert response.errors[0]["message"] == "Invalid cursor"
