"""Is the service up? Checked from inside the box, with the commands an operator uses."""

import json

import paramiko

from linux_ssh.remote import run


def test_process_runs_as_the_app_user(ssh: paramiko.SSHClient) -> None:
    pid = run(ssh, "pgrep -u app -f demo_service.py").stdout.strip()
    owner = run(ssh, f"ps -o user= -p {pid}").stdout.strip()
    assert owner == "app"  # not root


def test_service_listens_on_its_port(ssh: paramiko.SSHClient) -> None:
    # -l listening, -t TCP, -n numeric, -H no header. (Without root, ss can't show which
    # process owns a socket, so -p would add nothing here; the pgrep test covers that.)
    listeners = run(ssh, "ss -ltnH 'sport = :8080'").stdout
    assert "0.0.0.0:8080" in listeners


def test_health_from_inside_the_box(ssh: paramiko.SSHClient) -> None:
    body = run(ssh, "curl -fsS http://localhost:8080/health").stdout
    assert json.loads(body) == {"status": "ok"}


def test_healthcheck_script_passes_on_the_box(ssh: paramiko.SSHClient) -> None:
    # The same script that cron runs and the Bats tests cover, run for real.
    result = run(ssh, "/usr/local/bin/healthcheck.sh http://localhost:8080/health 3 1")
    assert result.stdout.strip() == "healthy: http://localhost:8080/health (attempt 1/3)"
