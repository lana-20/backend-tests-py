"""Happy paths and input errors for queries and mutations, using variables throughout."""

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from graphql_api.app.db import ContactRow, MessageRow
from graphql_api.tests.client import GraphQLClient

CONTACTS = """
query Contacts($first: Int!) {
  contacts(first: $first) { edges { node { id name email } } }
}
"""

CONTACT = """
query Contact($id: ID!) {
  contact(id: $id) { id name email messages { body } }
}
"""

CREATE_CONTACT = """
mutation Create($input: CreateContactInput!) {
  createContact(input: $input) { id name email owner }
}
"""

SEND_MESSAGE = """
mutation Send($contactId: ID!, $body: String!) {
  sendMessage(contactId: $contactId, body: $body) { id body contact { id } }
}
"""


def count(engine: Engine, model: type[ContactRow] | type[MessageRow]) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def test_contacts_lists_only_the_callers_contacts(api: GraphQLClient) -> None:
    response = api.execute(CONTACTS, {"first": 10}, token="alice-token")

    assert response.status == 200
    assert response.errors == []
    nodes = [edge["node"] for edge in response.data["contacts"]["edges"]]
    assert nodes == [
        {"id": "1", "name": "Alice contact 1", "email": "alice.1@example.com"},
        {"id": "2", "name": "Alice contact 2", "email": "alice.2@example.com"},
        {"id": "3", "name": "Alice contact 3", "email": "alice.3@example.com"},
    ]


def test_contact_by_id_with_nested_messages(api: GraphQLClient) -> None:
    response = api.execute(CONTACT, {"id": "2"}, token="alice-token")

    assert response.errors == []
    assert response.data == {
        "contact": {
            "id": "2",
            "name": "Alice contact 2",
            "email": "alice.2@example.com",
            "messages": [{"body": "Message 1 to Alice contact 2"}, {"body": "Message 2 to Alice contact 2"}],
        }
    }


def test_missing_contact_is_null_not_an_error(api: GraphQLClient) -> None:
    # A design choice: "not found" for a nullable lookup is data (null), not an error.
    response = api.execute(CONTACT, {"id": "999"}, token="alice-token")
    assert response.errors == []
    assert response.data == {"contact": None}


def test_create_contact_writes_a_row(api: GraphQLClient, engine: Engine) -> None:
    variables = {"input": {"name": "Dana", "email": "dana@example.com"}}
    response = api.execute(CREATE_CONTACT, variables, token="alice-token")

    assert response.errors == []
    created = response.data["createContact"]
    assert created == {"id": "6", "name": "Dana", "email": "dana@example.com", "owner": "alice"}
    with Session(engine) as session:
        row = session.get_one(ContactRow, 6)
        assert (row.owner, row.name, row.email) == ("alice", "Dana", "dana@example.com")


def test_create_contact_rejects_a_bad_email(api: GraphQLClient, engine: Engine) -> None:
    variables = {"input": {"name": "Dana", "email": "not-an-email"}}
    response = api.execute(CREATE_CONTACT, variables, token="alice-token")

    assert response.status == 200  # still 200: the error is in the body
    assert response.data is None  # createContact is non-null, so the null bubbles up to data
    assert response.error_codes == ["BAD_USER_INPUT"]
    assert response.errors[0]["path"] == ["createContact"]
    assert count(engine, ContactRow) == 5


def test_send_message_to_own_contact(api: GraphQLClient, engine: Engine) -> None:
    response = api.execute(SEND_MESSAGE, {"contactId": "1", "body": "Hello"}, token="alice-token")

    assert response.errors == []
    assert response.data["sendMessage"]["body"] == "Hello"
    assert response.data["sendMessage"]["contact"] == {"id": "1"}
    assert count(engine, MessageRow) == 11


def test_send_message_to_someone_elses_contact_is_not_found(api: GraphQLClient, engine: Engine) -> None:
    # Contact 4 is bob's. Alice gets the same answer as for an id that doesn't exist.
    response = api.execute(SEND_MESSAGE, {"contactId": "4", "body": "Hi"}, token="alice-token")

    assert response.error_codes == ["NOT_FOUND"]
    assert count(engine, MessageRow) == 10


def test_variable_of_the_wrong_type_is_rejected_before_execution(api: GraphQLClient) -> None:
    response = api.execute(CONTACTS, {"first": "ten"}, token="alice-token")

    assert response.data is None  # nothing ran
    assert "Int cannot represent non-integer value" in response.errors[0]["message"]
