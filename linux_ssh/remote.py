"""Run a command on the box over SSH and keep everything a reviewer needs to see."""

from dataclasses import dataclass

import allure
import paramiko


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    def __str__(self) -> str:
        return (
            f"$ {self.command}\nexit code: {self.exit_code}\n"
            f"--- stdout ---\n{self.stdout}\n--- stderr ---\n{self.stderr}"
        )


def run(client: paramiko.SSHClient, command: str, *, check: bool = True, timeout: float = 30) -> CommandResult:
    """Run `command`; attach command, exit code, stdout and stderr to the Allure report.

    With check=True (the default), a non-zero exit code fails the test with all of that
    in the message, so a failure explains itself without re-running anything.
    """
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    # Read both streams fully before asking for the exit code. (The outputs here are
    # small; a command printing megabytes would need the streams read concurrently.)
    out = stdout.read().decode()
    err = stderr.read().decode()
    result = CommandResult(command, stdout.channel.recv_exit_status(), out, err)

    allure.attach(str(result), name=f"$ {command}", attachment_type=allure.attachment_type.TEXT)
    if check and result.exit_code != 0:
        raise AssertionError(f"Command failed on the box:\n{result}")
    return result
