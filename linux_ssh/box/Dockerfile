# A small Linux "server" for smoke tests over SSH: sshd, a demo HTTP service under a
# process supervisor, cron and logrotate. Built fresh by the tests; never pushed anywhere.
FROM debian:13.8-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        openssh-server supervisor sudo cron logrotate \
        python3 curl ca-certificates procps iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Two accounts with separate jobs:
# - app:    runs the service; can't log in.
# - tester: the SSH login for smoke tests; can read logs (group adm), nothing more.
# tester's password field is "*": no password can ever match, but the account isn't
# "locked" ("!"), which some sshd setups treat as "no logins at all, keys included".
RUN useradd --system --create-home --shell /usr/sbin/nologin app \
    && useradd --create-home --shell /bin/bash --groups adm tester \
    && usermod --password '*' tester

COPY box/demo_service.py /opt/demo/demo_service.py
COPY box/demo.conf /etc/demo/demo.conf
COPY scripts/healthcheck.sh /usr/local/bin/healthcheck.sh
COPY box/supervisord.conf /etc/supervisor/conf.d/demo.conf
COPY box/logrotate-demo /etc/logrotate.d/demo
COPY box/cron-demo-healthcheck /etc/cron.d/demo-healthcheck
COPY box/sshd-hardening.conf /etc/ssh/sshd_config.d/10-hardening.conf
COPY box/sudoers-tester /etc/sudoers.d/tester
COPY box/entrypoint.sh /entrypoint.sh

# Ownership and modes are part of what the tests check, so set them explicitly.
# Host keys are deleted here and generated when a container starts (entrypoint.sh),
# so no two containers share a key and none is ever baked into the image.
RUN chown root:app /etc/demo/demo.conf && chmod 0640 /etc/demo/demo.conf \
    && chmod 0755 /usr/local/bin/healthcheck.sh /entrypoint.sh \
    && chmod 0644 /etc/logrotate.d/demo /etc/cron.d/demo-healthcheck /opt/demo/demo_service.py \
    && chmod 0440 /etc/sudoers.d/tester \
    && install -d -o app -g adm -m 0750 /var/log/demo \
    && install -d -m 0755 /run/sshd \
    && rm -f /etc/ssh/ssh_host_*

EXPOSE 22 8080
ENTRYPOINT ["/entrypoint.sh"]
