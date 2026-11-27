#!/bin/sh
# Container start: install the test session's public key, create fresh host keys,
# then hand over to supervisord, which runs sshd, cron and the demo service.
set -eu

: "${AUTHORIZED_KEY:?AUTHORIZED_KEY must be set to an SSH public key}"
install -d -o tester -g tester -m 0700 /home/tester/.ssh
printf '%s\n' "$AUTHORIZED_KEY" > /home/tester/.ssh/authorized_keys
chown tester:tester /home/tester/.ssh/authorized_keys
chmod 0600 /home/tester/.ssh/authorized_keys

# A new host key per container. Its public half goes to the log, so the test client can
# pin it instead of blindly trusting whatever answers on the port.
ssh-keygen -q -t ed25519 -N '' -f /etc/ssh/ssh_host_ed25519_key
echo "HOST_KEY $(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"

exec /usr/bin/supervisord --nodaemon --configuration /etc/supervisor/supervisord.conf
