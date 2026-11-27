"""Authentication per operation, and authorization per field."""

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from graphql_api.app.db import ContactRow
from graphql_api.tests.client import GraphQLClient

CONTACTS = "query { contacts { edges { node { id owner } } } }"
CONTACT_EMAIL = 'query { contact(id: "1") { name email } }'


@pytest.mark.parametrize("token", [None, "made-up-token"], ids=["no token", "unknown token"])
def test_operations_require_a_signed_in_user(api: GraphQLClient, token: str | None) -> None:
    response = api.execute(CONTACTS, token=token)

    # REST would answer 401. GraphQL answers 200, puts the error in the body, and nulls
    # the field. `contacts` is non-null, so the null propagates up to `data` itself.
    assert response.status == 200
    assert response.data is None
    assert response.error_codes == ["UNAUTHENTICATED"]
    assert response.errors[0]["path"] == ["contacts"]


def test_mutations_require_a_signed_in_user(api: GraphQLClient, engine: Engine) -> None:
    response = api.execute('mutation { createContact(input: {name: "X", email: "x@example.com"}) { id } }')

    assert response.error_codes == ["UNAUTHENTICATED"]
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ContactRow)) == 5


def test_owner_sees_the_email(api: GraphQLClient) -> None:
    response = api.execute(CONTACT_EMAIL, token="alice-token")
    assert response.errors == []
    assert response.data == {"contact": {"name": "Alice contact 1", "email": "alice.1@example.com"}}


def test_other_user_gets_partial_data_and_a_field_error(api: GraphQLClient) -> None:
    """The core GraphQL error shape: data and errors side by side."""
    response = api.execute(CONTACT_EMAIL, token="bob-token")

    assert response.status == 200
    # The fields bob may see are there; the one he may not is null...
    assert response.data == {"contact": {"name": "Alice contact 1", "email": None}}
    # ...and the error says exactly which field, and why.
    assert len(response.errors) == 1
    error = response.errors[0]
    assert error["path"] == ["contact", "email"]
    assert error["extensions"] == {"code": "FORBIDDEN"}
    assert error["message"] == "Only the contact's owner can see this field"


def test_admin_sees_every_email(api: GraphQLClient) -> None:
    response = api.execute(CONTACT_EMAIL, token="admin-token")
    assert response.data["contact"]["email"] == "alice.1@example.com"


def test_admin_lists_everyones_contacts(api: GraphQLClient) -> None:
    response = api.execute(CONTACTS, token="admin-token")
    owners = [edge["node"]["owner"] for edge in response.data["contacts"]["edges"]]
    assert owners == ["alice", "alice", "alice", "bob", "bob"]
