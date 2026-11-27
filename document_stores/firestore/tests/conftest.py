import os
from collections.abc import Iterator
from uuid import uuid4

import allure
import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from document_stores.firestore.rest_client import EmulatorRestClient

# The Google Cloud CLI image variant that bundles the emulators (and a Java runtime).
EMULATOR_IMAGE = "gcr.io/google.com/cloudsdktool/google-cloud-cli:594.0.1-emulators"


@pytest.fixture(autouse=True)
def _allure_labels() -> None:
    allure.dynamic.parent_suite("Firestore emulator")


@pytest.fixture(scope="session")
def emulator_host() -> Iterator[str]:
    container = (
        DockerContainer(EMULATOR_IMAGE)
        .with_command("gcloud emulators firestore start --host-port=0.0.0.0:8080")
        .with_exposed_ports(8080)
        .waiting_for(LogMessageWaitStrategy("Dev App Server is now running").with_startup_timeout(180))
    )
    with container:
        host = f"{container.get_container_host_ip()}:{container.get_exposed_port(8080)}"
        # The client library switches to the emulator when this variable is set.
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("FIRESTORE_EMULATOR_HOST", host)
            yield host


@pytest.fixture
def project() -> str:
    # The emulator keeps a separate database per project id. A new id per test means
    # full isolation with no cleanup. The "demo-" prefix marks a project that doesn't
    # exist in Google Cloud, so nothing can ever reach a real one.
    return f"demo-{uuid4().hex[:12]}"


@pytest.fixture
def db(emulator_host: str, project: str) -> firestore.Client:
    assert os.environ["FIRESTORE_EMULATOR_HOST"] == emulator_host
    return firestore.Client(project=project, credentials=AnonymousCredentials())


@pytest.fixture
def rest(emulator_host: str, project: str) -> EmulatorRestClient:
    return EmulatorRestClient(emulator_host, project)
