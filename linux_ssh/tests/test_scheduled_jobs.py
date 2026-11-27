"""Cron and logrotate: the config is valid and points at things that exist."""

import paramiko

from linux_ssh.remote import run


def test_cron_is_running(ssh: paramiko.SSHClient) -> None:
    run(ssh, "pgrep -x cron")


def test_cron_entry_is_well_formed(ssh: paramiko.SSHClient) -> None:
    lines = run(ssh, "grep -v '^#' /etc/cron.d/demo-healthcheck | grep -v '^$'").stdout.splitlines()
    assert len(lines) == 1
    # /etc/cron.d format: 5 schedule fields, a user, then the command.
    minute, hour, day, month, weekday, user, command, *_arguments = lines[0].split()
    assert (minute, hour, day, month, weekday) == ("*/5", "*", "*", "*", "*")
    assert user == "app"
    run(ssh, f"test -x {command}")  # the script exists and is executable


def test_cron_file_has_safe_ownership(ssh: paramiko.SSHClient) -> None:
    # cron ignores /etc/cron.d files that aren't owned by root or are group/world-writable.
    assert run(ssh, "stat -c '%U %a' /etc/cron.d/demo-healthcheck").stdout.strip() == "root 644"


def test_logrotate_config_is_valid(ssh: paramiko.SSHClient) -> None:
    # -d: debug/dry run, changes nothing. A syntax error makes logrotate exit non-zero.
    # It runs via sudo because `su app adm` in the config needs root even in a dry run;
    # sudoers allows exactly this command line and no other.
    result = run(ssh, "sudo -n /usr/sbin/logrotate -d /etc/logrotate.d/demo")
    report = result.stdout + result.stderr
    assert "rotating pattern: /var/log/demo/*.log" in report
    assert "error:" not in report
