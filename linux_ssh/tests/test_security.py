"""Access control on the box: keys only, least privilege, protected config."""

import paramiko
import pytest

from linux_ssh.remote import run
from linux_ssh.tests.conftest import Box, connect, generate_key


def allowed_auth_methods(box: Box, username: str) -> list[str]:
    """Ask sshd which login methods it would accept for `username`.

    The "none" method always fails, and the error lists what the server allows.
    """
    transport = paramiko.Transport((box.host, box.ssh_port))
    try:
        transport.start_client(timeout=10)
        with pytest.raises(paramiko.BadAuthenticationType) as caught:
            transport.auth_none(username)
        return list(caught.value.allowed_types)
    finally:
        transport.close()


@pytest.mark.parametrize("username", ["tester", "root"])
def test_server_offers_public_key_login_only(box: Box, username: str) -> None:
    # No "password" or "keyboard-interactive": nobody can even try to guess a password.
    assert allowed_auth_methods(box, username) == ["publickey"]


def test_unknown_key_is_rejected(box: Box) -> None:
    with pytest.raises(paramiko.AuthenticationException):
        connect(box, generate_key())


def test_sshd_hardening_settings(ssh: paramiko.SSHClient) -> None:
    config = run(ssh, "cat /etc/ssh/sshd_config.d/10-hardening.conf").stdout.splitlines()
    for setting in ("PasswordAuthentication no", "PermitRootLogin no", "AllowUsers tester"):
        assert setting in config


def test_tester_is_not_root_and_has_no_general_sudo(ssh: paramiko.SSHClient) -> None:
    assert run(ssh, "id -un").stdout.strip() == "tester"
    # sudo -n: never prompt. Running anything as root must be refused...
    assert run(ssh, "sudo -n true", check=False).exit_code != 0
    # ...the single grant is "kill, as the app user" (used by the restart test).
    grants = run(ssh, "sudo -n -l").stdout
    assert "(app) NOPASSWD: /usr/bin/kill" in grants


def test_config_file_ownership_and_mode(ssh: paramiko.SSHClient) -> None:
    # root owns it, the service's group can read it, nobody else can.
    assert run(ssh, "stat -c '%U:%G %a' /etc/demo/demo.conf").stdout.strip() == "root:app 640"
    # And that really holds for this login, which is not in group app:
    denied = run(ssh, "cat /etc/demo/demo.conf", check=False)
    assert denied.exit_code != 0
    assert "Permission denied" in denied.stderr


def test_nothing_world_writable_in_service_paths(ssh: paramiko.SSHClient) -> None:
    # -perm -o+w matches anything others can write to; the output must be empty.
    found = run(ssh, "find /etc/demo /opt/demo /usr/local/bin /etc/cron.d /etc/logrotate.d -perm -o+w").stdout
    assert found == ""


def test_authorized_keys_permissions(ssh: paramiko.SSHClient) -> None:
    # sshd ignores authorized_keys that others could edit; check it the way sshd would.
    assert run(ssh, "stat -c '%U %a' ~/.ssh ~/.ssh/authorized_keys").stdout.split("\n")[:2] == [
        "tester 700",
        "tester 600",
    ]
