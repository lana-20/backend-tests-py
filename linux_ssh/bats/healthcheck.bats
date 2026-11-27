#!/usr/bin/env bats
# Tests for scripts/healthcheck.sh. curl is replaced by a stub on PATH, so the tests
# need no network and no server, and the stub decides each attempt's outcome.

setup() {
  STUB_DIR="$(mktemp -d)"
  export CALLS_FILE="$STUB_DIR/calls"
  : > "$CALLS_FILE"
  # Fake curl: records each call, then exits with the next code from CURL_EXIT_CODES
  # (the last code repeats). 22 is what real curl -f returns for an HTTP error.
  cat > "$STUB_DIR/curl" <<'STUB'
#!/usr/bin/env bash
echo "$*" >> "$CALLS_FILE"
n=$(wc -l < "$CALLS_FILE")
exit "$(echo "$CURL_EXIT_CODES" | awk -v n="$n" '{ print (n <= NF) ? $n : $NF }')"
STUB
  chmod +x "$STUB_DIR/curl"
  PATH="$STUB_DIR:$PATH"
  SCRIPT="$BATS_TEST_DIRNAME/../scripts/healthcheck.sh"
}

teardown() {
  rm -rf "$STUB_DIR"
}

curl_calls() {
  wc -l < "$CALLS_FILE" | tr -d ' '
}

@test "healthy on the first attempt" {
  export CURL_EXIT_CODES="0"
  run "$SCRIPT" http://localhost:8080/health 3 0
  [ "$status" -eq 0 ]
  [ "$output" = "healthy: http://localhost:8080/health (attempt 1/3)" ]
  [ "$(curl_calls)" -eq 1 ]
}

@test "retries until the service comes up" {
  export CURL_EXIT_CODES="7 22 0"   # refused, then HTTP error, then OK
  run "$SCRIPT" http://localhost:8080/health 5 0
  [ "$status" -eq 0 ]
  [[ "$output" == *"healthy: http://localhost:8080/health (attempt 3/5)"* ]]
  [ "$(curl_calls)" -eq 3 ]
}

@test "gives up after the last attempt with exit code 1" {
  export CURL_EXIT_CODES="22"
  run "$SCRIPT" http://localhost:8080/health 3 0
  [ "$status" -eq 1 ]
  [[ "$output" == *"unhealthy: http://localhost:8080/health after 3 attempts"* ]]
  [ "$(curl_calls)" -eq 3 ]
}

@test "passes fail-fast flags to curl" {
  export CURL_EXIT_CODES="0"
  run "$SCRIPT" http://localhost:8080/health 1 0
  # -f makes 4xx/5xx count as failures; --max-time stops a hung port from blocking.
  [[ "$(cat "$CALLS_FILE")" == *"-fsS --max-time 5"* ]]
}

@test "no URL is a usage error (exit 2)" {
  run "$SCRIPT"
  [ "$status" -eq 2 ]
  [[ "$output" == usage:* ]]
}

@test "non-numeric attempts is a usage error (exit 2)" {
  run "$SCRIPT" http://localhost:8080/health many
  [ "$status" -eq 2 ]
  [ "$(curl_calls)" -eq 0 ]
}
