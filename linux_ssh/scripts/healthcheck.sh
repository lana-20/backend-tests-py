#!/usr/bin/env bash
# Usage: healthcheck.sh URL [ATTEMPTS] [INTERVAL_SECONDS]
#
# Polls URL until it answers with a 2xx status. Used after a deploy, and by cron.
# Exit codes: 0 healthy, 1 still unhealthy after ATTEMPTS tries, 2 bad usage.
set -euo pipefail

usage() {
  echo "usage: $(basename "$0") URL [ATTEMPTS] [INTERVAL_SECONDS]" >&2
  exit 2
}

[[ $# -ge 1 && $# -le 3 ]] || usage
url=$1
attempts=${2:-5}
interval=${3:-2}
[[ $attempts =~ ^[1-9][0-9]*$ ]] || usage
[[ $interval =~ ^[0-9]+$ ]] || usage

for ((i = 1; i <= attempts; i++)); do
  # -f: treat HTTP errors (4xx/5xx) as failure. --max-time: never hang on a dead port.
  if curl -fsS --max-time 5 -o /dev/null "$url"; then
    echo "healthy: $url (attempt $i/$attempts)"
    exit 0
  fi
  echo "not healthy yet: $url (attempt $i/$attempts)" >&2
  if ((i < attempts)); then
    sleep "$interval"
  fi
done

echo "unhealthy: $url after $attempts attempts" >&2
exit 1
