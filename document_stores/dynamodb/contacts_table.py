"""A contacts table in DynamoDB, and the access patterns the app needs.

DynamoDB is designed around access patterns, not around a schema: the key decides which
queries are cheap. Here:
- partition key `owner`, sort key `contact_id`: "all contacts of one owner" is a Query.
- global secondary index `by_email`: "find a contact by email" is a Query on the index.
Anything else is a Scan, which reads (and bills for) the whole table.
"""

from collections.abc import Iterator
from typing import Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

Item = dict[str, Any]


class StaleWriteError(Exception):
    """Someone else changed the item since we read it (optimistic locking)."""


class AlreadyExistsError(Exception):
    pass


def create_table(dynamodb: Any, name: str) -> Any:
    table = dynamodb.create_table(
        TableName=name,
        KeySchema=[
            {"AttributeName": "owner", "KeyType": "HASH"},
            {"AttributeName": "contact_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "owner", "AttributeType": "S"},
            {"AttributeName": "contact_id", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "by_email",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    # TTL: DynamoDB deletes an item some time after the epoch-seconds in `expires_at`.
    dynamodb.meta.client.update_time_to_live(
        TableName=name, TimeToLiveSpecification={"Enabled": True, "AttributeName": "expires_at"}
    )
    return table


def is_conditional_check_failure(error: ClientError) -> bool:
    return bool(error.response["Error"]["Code"] == "ConditionalCheckFailedException")


def put_new_contact(table: Any, item: Item) -> None:
    """Insert, but never overwrite: a plain put_item silently replaces an existing item."""
    try:
        table.put_item(
            Item=item | {"version": 1},
            ConditionExpression=Attr("contact_id").not_exists(),
        )
    except ClientError as error:
        if is_conditional_check_failure(error):
            raise AlreadyExistsError(item["contact_id"]) from error
        raise


def rename_contact(table: Any, owner: str, contact_id: str, name: str, expected_version: int) -> int:
    """Update only if the item still has the version we read. Returns the new version."""
    try:
        response = table.update_item(
            Key={"owner": owner, "contact_id": contact_id},
            UpdateExpression="SET #name = :name, version = version + :one",
            ConditionExpression=Attr("version").eq(expected_version),
            # "name" is a DynamoDB reserved word, hence the #name placeholder.
            ExpressionAttributeNames={"#name": "name"},
            ExpressionAttributeValues={":name": name, ":one": 1},
            ReturnValues="UPDATED_NEW",
        )
    except ClientError as error:
        if is_conditional_check_failure(error):
            raise StaleWriteError(contact_id) from error
        raise
    return int(response["Attributes"]["version"])


def contact_pages(table: Any, owner: str, page_size: int) -> Iterator[list[Item]]:
    """Yield one owner's contacts a page at a time, following LastEvaluatedKey."""
    kwargs: dict[str, Any] = {"KeyConditionExpression": Key("owner").eq(owner), "Limit": page_size}
    while True:
        response = table.query(**kwargs)
        yield response["Items"]
        if "LastEvaluatedKey" not in response:
            return
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def find_by_email(table: Any, email: str) -> list[Item]:
    response = table.query(IndexName="by_email", KeyConditionExpression=Key("email").eq(email))
    return list(response["Items"])


def active_contacts(table: Any, owner: str, now: int) -> list[Item]:
    """Contacts that have no expiry, or haven't reached it yet.

    TTL deletion is a background process: real DynamoDB typically removes expired items
    within a few days, and DynamoDB Local never does. Reads must filter them out.
    """
    response = table.query(
        KeyConditionExpression=Key("owner").eq(owner),
        FilterExpression=Attr("expires_at").not_exists() | Attr("expires_at").gt(now),
    )
    return list(response["Items"])
