"""DynamoDB access patterns against DynamoDB Local."""

from typing import Any

import pytest
from botocore.exceptions import ClientError

from document_stores.dynamodb.contacts_table import (
    AlreadyExistsError,
    StaleWriteError,
    active_contacts,
    contact_pages,
    find_by_email,
    put_new_contact,
    rename_contact,
)


def contact(owner: str, n: int, **extra: Any) -> dict[str, Any]:
    return {
        "owner": owner,
        "contact_id": f"c{n:03d}",
        "name": f"{owner} {n}",
        "email": f"{owner}{n}@example.com",
    } | extra


def add_contacts(table: Any, owner: str, count: int) -> None:
    for n in range(1, count + 1):
        put_new_contact(table, contact(owner, n))


# --- Conditional writes ----------------------------------------------------------------


def test_conditional_put_does_not_overwrite(table: Any) -> None:
    put_new_contact(table, contact("alice", 1))

    with pytest.raises(AlreadyExistsError):
        put_new_contact(table, contact("alice", 1, name="Overwritten?"))

    item = table.get_item(Key={"owner": "alice", "contact_id": "c001"})["Item"]
    assert item["name"] == "alice 1"


def test_optimistic_locking_with_a_version_attribute(table: Any) -> None:
    put_new_contact(table, contact("alice", 1))

    # Two clients both read version 1. The first write wins and bumps the version...
    assert rename_contact(table, "alice", "c001", "First writer", expected_version=1) == 2
    # ...so the second, still holding version 1, is rejected instead of overwriting.
    with pytest.raises(StaleWriteError):
        rename_contact(table, "alice", "c001", "Second writer", expected_version=1)

    item = table.get_item(Key={"owner": "alice", "contact_id": "c001"})["Item"]
    assert (item["name"], item["version"]) == ("First writer", 2)


# --- Query vs Scan ---------------------------------------------------------------------


def test_query_reads_one_partition_scan_reads_the_table(table: Any) -> None:
    for owner in ("alice", "bob", "cy"):
        add_contacts(table, owner, 5)

    query = table.query(
        KeyConditionExpression="#o = :o",
        ExpressionAttributeNames={"#o": "owner"},
        ExpressionAttributeValues={":o": "alice"},
    )
    scan = table.scan(
        FilterExpression="#o = :o", ExpressionAttributeNames={"#o": "owner"}, ExpressionAttributeValues={":o": "alice"}
    )

    # Same answer...
    assert query["Count"] == scan["Count"] == 5
    # ...but the scan examined (and would bill for) every item, then threw most away.
    assert query["ScannedCount"] == 5
    assert scan["ScannedCount"] == 15


def test_lookup_through_the_global_secondary_index(table: Any) -> None:
    add_contacts(table, "alice", 3)
    assert [item["contact_id"] for item in find_by_email(table, "alice2@example.com")] == ["c002"]


def test_gsi_reads_cannot_be_strongly_consistent(table: Any) -> None:
    # GSIs are updated asynchronously in real DynamoDB, so a read right after a write
    # may miss it. The API refuses to pretend otherwise. (DynamoDB Local updates the
    # index immediately, which is one way it is kinder than production.)
    with pytest.raises(ClientError) as caught:
        table.query(
            IndexName="by_email",
            KeyConditionExpression="email = :e",
            ExpressionAttributeValues={":e": "x@example.com"},
            ConsistentRead=True,
        )
    assert caught.value.response["Error"]["Code"] == "ValidationException"


# --- Pagination ------------------------------------------------------------------------


def test_pages_follow_last_evaluated_key(table: Any) -> None:
    add_contacts(table, "alice", 5)

    pages = list(contact_pages(table, "alice", page_size=2))

    assert [len(page) for page in pages] == [2, 2, 1]
    ids = [item["contact_id"] for page in pages for item in page]
    assert ids == ["c001", "c002", "c003", "c004", "c005"]  # sorted by the sort key, no repeats


def test_exact_multiple_ends_with_an_empty_page(table: Any) -> None:
    # A gotcha: when a page fills up exactly, DynamoDB returns a LastEvaluatedKey without
    # knowing if more items exist. The client must be ready for a final empty page.
    add_contacts(table, "alice", 4)
    assert [len(page) for page in contact_pages(table, "alice", page_size=2)] == [2, 2, 0]


# --- TTL -------------------------------------------------------------------------------

NOW = 1_800_000_000  # a fixed "now" (epoch seconds), so the test doesn't depend on the clock


def test_ttl_is_enabled_on_expires_at(table: Any, dynamodb: Any) -> None:
    description = dynamodb.meta.client.describe_time_to_live(TableName=table.name)["TimeToLiveDescription"]
    assert description == {"TimeToLiveStatus": "ENABLED", "AttributeName": "expires_at"}


def test_expired_items_are_filtered_on_read(table: Any) -> None:
    put_new_contact(table, contact("alice", 1))  # never expires
    put_new_contact(table, contact("alice", 2, expires_at=NOW + 60))  # expires in a minute
    put_new_contact(table, contact("alice", 3, expires_at=NOW - 60))  # expired a minute ago

    # The expired item is still stored: DynamoDB Local never runs TTL deletion.
    assert table.get_item(Key={"owner": "alice", "contact_id": "c003"}).get("Item") is not None
    # The read path filters it out anyway, as it must with real DynamoDB too.
    assert [item["contact_id"] for item in active_contacts(table, "alice", now=NOW)] == ["c001", "c002"]
