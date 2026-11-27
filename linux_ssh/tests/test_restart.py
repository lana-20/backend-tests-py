"""Kill the service and check that the supervisor brings it back."""

import paramiko
import requests

from common.polling import wait_until
from linux_ssh.remote import run
from linux_ssh.tests.conftest import Box


def service_pid(ssh: paramiko.SSHClient) -> str | None:
    result = run(ssh, "pgrep -u app -f demo_service.py", check=False)
    return result.stdout.strip() or None


def test_supervisor_restarts_a_killed_service(box: Box, ssh: paramiko.SSHClient) -> None:
    old_pid = service_pid(ssh)
    assert old_pid is not None

    # SIGKILL: no graceful shutdown, like a crash or the OOM killer. tester may only
    # do this as the app user (see sudoers-tester).
    run(ssh, f"sudo -n -u app /usr/bin/kill -KILL {old_pid}")

    # The restart happens asynchronously in supervisord; polling for it is the
    # inherent wait. A new PID proves it's a new process, not the old one surviving.
    new_pid = wait_until(
        lambda: (pid := service_pid(ssh)) != old_pid and pid,
        timeout=20,
        description="supervisord to restart the service",
    )
    assert new_pid != old_pid
    wait_until(
        lambda: requests.get(f"{box.http_url}/health", timeout=2).ok,
        timeout=20,
        description="the restarted service to answer",
        ignore=(requests.ConnectionError,),
    )
