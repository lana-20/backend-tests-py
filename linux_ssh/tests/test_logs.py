"""Trace one request from the outside into the service's log."""

from uuid import uuid4

import paramiko
import requests

from linux_ssh.remote import run
from linux_ssh.tests.conftest import Box

LOG = "/var/log/demo/app.log"


def test_request_id_appears_in_the_log(box: Box, ssh: paramiko.SSHClient) -> None:
    request_id = f"smoke-{uuid4()}"
    response = requests.get(f"{box.http_url}/api/hello", headers={"X-Request-ID": request_id}, timeout=10)
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == request_id

    # Exactly one line for this request, and it records the right path and status.
    lines = run(ssh, f"grep -F 'request_id={request_id}' {LOG}").stdout.splitlines()
    assert len(lines) == 1
    fields = dict(field.split("=", 1) for field in lines[0].split() if "=" in field)
    assert (fields["path"], fields["status"]) == ("/api/hello", "200")


def test_no_error_lines_in_the_recent_log(ssh: paramiko.SSHClient) -> None:
    # awk counts lines whose level (third column) is ERROR or CRITICAL. grep -c would
    # also count "ERROR" inside a request path; matching the column avoids that.
    count = run(ssh, f'tail -n 500 {LOG} | awk \'$3 == "ERROR" || $3 == "CRITICAL"\' | wc -l').stdout
    assert int(count) == 0


def test_log_directory_is_closed_to_other_users(ssh: paramiko.SSHClient) -> None:
    # The directory is the gate: owned by the service, readable by group adm (log
    # readers, which tester is in), and closed to everyone else.
    assert run(ssh, "stat -c '%U:%G %a' /var/log/demo").stdout.strip() == "app:adm 750"
