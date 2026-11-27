# Linux servers over SSH, and Bats

Smoke tests for a deployed box, written the way an operator would check it by hand:
log in over SSH and run real commands. The "server" is a Debian container
([`box/Dockerfile`](box/Dockerfile)) running `sshd`, `cron` and a small HTTP service
under `supervisord`. Tests use Paramiko.

```bash
uv run pytest linux_ssh    # needs Docker: builds and starts the box
bats linux_ssh/bats        # Bats tests for the healthcheck script; no Docker
```

Every command goes through one helper, [`remote.py`](remote.py), which captures the exit
code, stdout and stderr, attaches all three to the Allure report, and fails with all of
them in the message. A failing check explains itself.

## What it covers

| Check | Commands |
|---|---|
| The service runs, as its own user | `pgrep -u app -f`, `ps -o user=` |
| It listens on its port | `ss -ltnH 'sport = :8080'` |
| Health from inside the box | `curl -fsS localhost:8080/health`, plus the real `healthcheck.sh` |
| Config and key file ownership and modes; nothing world-writable | `stat -c '%U:%G %a'`, `find -perm -o+w`, a `cat` that must be denied |
| A request sent through the API shows up in the log with its request id; no ERROR lines | `grep -F`, `tail \| awk` |
| Disk and memory headroom | `df -Pm`, `free -m \| awk` |
| A killed service comes back under the supervisor, with a new PID | `sudo -u app kill -KILL`, then poll `pgrep` |
| Cron entry well-formed and pointing at an executable; cron running; logrotate config valid | `stat`, `test -x`, `logrotate -d` |
| Only public-key login is offered (for `tester` and `root`); an unknown key is refused; sudo is limited | Paramiko `auth_none`, `sudo -n -l` |

**Bats** ([`bats/healthcheck.bats`](bats/healthcheck.bats)) tests
[`scripts/healthcheck.sh`](scripts/healthcheck.sh), the script a deploy pipeline (and
the box's cron job) uses to wait for a healthy service. `curl` is replaced by a stub on
`PATH` that fails or succeeds on cue, so retries, give-up and usage errors are tested
without a network. CI runs Bats from npm, pinned (`bats@1.13.0`), and feeds its JUnit
output into the Allure report.

**Cost:** about 40 seconds (image build and start-up); Bats under a second.

## Security choices

- **Ephemeral keys.** Each test session generates a new Ed25519 key pair in memory. Only
  the public key leaves the process (as an environment variable for the container). No
  key is ever written to disk or committed.
- **No passwords.** `sshd` offers `publickey` only; the test asks the server which methods
  it accepts and requires exactly that. The login user's password field is `*`, which
  nothing can match.
- **Pinned host key.** The box generates new host keys at start and prints the public one;
  the client adds it to known hosts and uses `RejectPolicy`. No `AutoAddPolicy`, so a
  man-in-the-middle would be refused, not trusted.
- **Least privilege.** The service runs as `app`; the SSH user `tester` is a different,
  unprivileged account that can read logs (group `adm`) but not the service's config. Its
  sudo rights are two exact command lines: `kill` as `app` (for the restart test) and one
  logrotate dry run. No root login, no TCP forwarding.

## When to use this, and when infrastructure-as-code tools

These checks answer "is this box healthy right now, from the inside?" They're quick to
write, need nothing on the box but `sshd`, and read like an operator's runbook, so they
suit post-deploy smoke tests, legacy or hand-built servers, and incident checklists.

Tools like Testinfra, InSpec or Goss (and the IaC tools themselves: Ansible, Terraform)
fit better when you own the box's configuration as code: they test desired state
declaratively, cover many hosts, and plug into the provisioning pipeline. Most teams
need both: IaC tests to say "the config is right", smoke tests to say "and it actually
works after this deploy".
