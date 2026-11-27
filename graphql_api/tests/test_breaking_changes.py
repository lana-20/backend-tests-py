"""Self-test of the breaking-change gate: prove it fails on a broken schema.

A gate that never fails is worse than no gate, because it looks like protection. CI
runs these tests before it compares the schema with the base branch.
"""

from pathlib import Path

import pytest

from graphql_api.breaking_changes import breaking_changes, dangerous_changes, main
from graphql_api.tests.test_schema_contract import SDL_FILE

CURRENT = SDL_FILE.read_text()


def edited(old: str, new: str) -> str:
    assert old in CURRENT, f"the self-test edit no longer applies: {old!r}"
    return CURRENT.replace(old, new)


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        # Removing a field breaks every client that selects it.
        ("  email: String\n", "", "FIELD_REMOVED: Field Contact.email was removed."),
        # Changing a field's type breaks clients that parse it.
        (
            "  owner: String!\n",
            "  owner: Int!\n",
            "FIELD_CHANGED_KIND: Field Contact.owner changed type from String! to Int!.",
        ),
        # A new required argument breaks every existing call.
        (
            "  contact(id: ID!): Contact\n",
            "  contact(id: ID!, tenant: String!): Contact\n",
            "REQUIRED_ARG_ADDED: A required argument Query.contact(tenant:) was added.",
        ),
        # Making an input field required breaks clients that omit it.
        (
            "input CreateContactInput {\n  name: String!\n  email: String!\n}",
            "input CreateContactInput {\n  name: String!\n  email: String!\n  phone: String!\n}",
            "REQUIRED_INPUT_FIELD_ADDED: A required field CreateContactInput.phone was added.",
        ),
    ],
    ids=["field removed", "field type changed", "required argument added", "required input field added"],
)
def test_gate_reports_breaking_changes(old: str, new: str, expected: str) -> None:
    assert breaking_changes(CURRENT, edited(old, new)) == [expected]


def test_additive_changes_are_not_breaking() -> None:
    # A new optional field and a new optional argument: old clients keep working.
    new = edited("  email: String\n", "  email: String\n  nickname: String\n")
    new = new.replace(
        "  contact(id: ID!): Contact\n", "  contact(id: ID!, includeArchived: Boolean = false): Contact\n"
    )
    assert breaking_changes(CURRENT, new) == []


def test_new_optional_argument_default_change_is_flagged_as_dangerous() -> None:
    new = edited("contacts(first: Int! = 10", "contacts(first: Int! = 20")
    assert breaking_changes(CURRENT, new) == []
    assert dangerous_changes(CURRENT, new) == [
        "ARG_DEFAULT_VALUE_CHANGE: Query.contacts(first:) has changed defaultValue from 10 to 20."
    ]


def test_command_line_exit_codes(tmp_path: Path) -> None:
    unchanged, broken = tmp_path / "unchanged.graphql", tmp_path / "broken.graphql"
    unchanged.write_text(CURRENT)
    broken.write_text(edited("  email: String\n", ""))

    assert main([str(SDL_FILE), str(unchanged)]) == 0
    assert main([str(SDL_FILE), str(broken)]) == 1
