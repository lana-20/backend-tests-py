from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import allure
import boto3
import pytest
from botocore.exceptions import BotoCoreError
from testcontainers.core.container import DockerContainer

from common.polling import wait_until
from document_stores.dynamodb.contacts_table import create_table

DYNAMODB_LOCAL_IMAGE = "amazon/dynamodb-local:3.3.2"


@pytest.fixture(autouse=True)
def _allure_labels() -> None:
    allure.dynamic.parent_suite("DynamoDB Local")


@pytest.fixture(scope="session")
def dynamodb() -> Iterator[Any]:
    container = (
        DockerContainer(DYNAMODB_LOCAL_IMAGE)
        .with_command("-jar DynamoDBLocal.jar -inMemory -sharedDb")
        .with_exposed_ports(8000)
    )
    with container:
        resource = boto3.resource(
            "dynamodb",
            endpoint_url=f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8000)}",
            # DynamoDB Local accepts any credentials; these are placeholders, not secrets.
            region_name="us-east-1",
            aws_access_key_id="local",
            aws_secret_access_key="local",
        )
        # The JVM inside needs a moment before it answers; poll until it does.
        wait_until(
            lambda: resource.meta.client.list_tables() is not None,
            timeout=60,
            description="DynamoDB Local to answer",
            ignore=(BotoCoreError,),
        )
        yield resource


@pytest.fixture
def table(dynamodb: Any) -> Iterator[Any]:
    """A new table per test: nothing shared between tests."""
    table = create_table(dynamodb, f"contacts-{uuid4().hex[:12]}")
    yield table
    table.delete()
