"""Headroom: enough disk for logs and enough free memory to keep serving."""

import paramiko

from linux_ssh.remote import run

MIN_FREE_DISK_MB = 1024
MIN_AVAILABLE_MEMORY_MB = 128


def test_disk_headroom_for_logs(ssh: paramiko.SSHClient) -> None:
    # df -P: one line per filesystem, stable columns. -m: sizes in MB. Column 4 = available.
    df = run(ssh, "df -Pm /var/log").stdout
    available_mb = int(df.splitlines()[1].split()[3])
    assert available_mb >= MIN_FREE_DISK_MB, df


def test_memory_headroom(ssh: paramiko.SSHClient) -> None:
    # The "available" column (7th) estimates memory usable without swapping; "free"
    # alone undercounts, because Linux uses spare memory as cache.
    free = run(ssh, "free -m").stdout
    available_mb = int(run(ssh, "free -m | awk '/^Mem:/ {print $7}'").stdout)
    assert available_mb >= MIN_AVAILABLE_MEMORY_MB, free
