"""Build the Linux box image, start it, and log in over SSH with a throwaway key.

Security choices, all per test session:
- a new Ed25519 key pair, generated in memory; only the public half leaves the process
- the box creates new host keys at start and prints the public one; the client pins it
  (RejectPolicy), instead of trusting whatever answers on the port
- no passwords anywhere: sshd allows public keys only
"""

import base64
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import allure
import paramiko
import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from common.polling import wait_until

LINUX_SSH_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _allure_labels() -> None:
    allure.dynamic.parent_suite("Linux over SSH")


@dataclass(frozen=True)
class Box:
    host: str
    ssh_port: int
    http_url: str  # the demo service, as seen from outside the box
    host_key: paramiko.PKey


def generate_key() -> paramiko.PKey:
    """A new Ed25519 key pair, in memory only. (Paramiko can't generate Ed25519 keys
    itself, so the cryptography package does, and Paramiko loads the result.)"""
    pem = (
        Ed25519PrivateKey.generate()
        .private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
        .decode()
    )
    return paramiko.Ed25519Key(file_obj=io.StringIO(pem))


@pytest.fixture(scope="session")
def client_key() -> paramiko.PKey:
    """This test session's login key. Never written to disk."""
    return generate_key()


@pytest.fixture(scope="session")
def box(client_key: paramiko.PKey) -> Iterator[Box]:
    with DockerImage(
        path=LINUX_SSH_DIR, dockerfile_path="box/Dockerfile", tag="backend-tests-py/ssh-box:test"
    ) as image:
        container = (
            DockerContainer(str(image))
            .with_env("AUTHORIZED_KEY", f"{client_key.get_name()} {client_key.get_base64()}")
            .with_exposed_ports(22, 8080)
            .waiting_for(LogMessageWaitStrategy("HOST_KEY"))
        )
        with container:
            logs = container.get_logs()[0].decode()
            match = re.search(r"HOST_KEY ssh-ed25519 (\S+)", logs)
            assert match, f"box did not print its host key:\n{logs}"
            box = Box(
                host=container.get_container_host_ip(),
                ssh_port=int(container.get_exposed_port(22)),
                http_url=f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8080)}",
                host_key=paramiko.Ed25519Key(data=base64.b64decode(match.group(1))),
            )
            # supervisord is still starting the service; wait until it answers.
            wait_until(
                lambda: requests.get(f"{box.http_url}/health", timeout=2).ok,
                timeout=60,
                description="the demo service to answer",
                ignore=(requests.ConnectionError,),
            )
            yield box


def connect(box: Box, key: paramiko.PKey, username: str = "tester") -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.get_host_keys().add(f"[{box.host}]:{box.ssh_port}", "ssh-ed25519", box.host_key)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())  # unknown host key: refuse
    client.connect(
        box.host,
        port=box.ssh_port,
        username=username,
        pkey=key,
        look_for_keys=False,  # don't pick up keys from the developer's ~/.ssh
        allow_agent=False,
        timeout=10,
    )
    return client


@pytest.fixture(scope="session")
def ssh(box: Box, client_key: paramiko.PKey) -> Iterator[paramiko.SSHClient]:
    # sshd may start a moment after the HTTP service; retrying the first connection is
    # the inherent wait here.
    client = wait_until(
        lambda: connect(box, client_key),
        timeout=30,
        description="sshd to accept the login",
        ignore=(paramiko.SSHException, OSError),
    )
    yield client
    client.close()
