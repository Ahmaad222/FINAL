#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SH="$ROOT_DIR/run.sh"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/zeinaguard-tests.XXXXXX")"
STUB_BIN="$TEST_ROOT/bin"
ARTIFACT_DIR="$TEST_ROOT/artifacts"
PATH_ORIG="$PATH"

mkdir -p "$STUB_BIN" "$ARTIFACT_DIR"

log() {
  printf '[test-run] %s\n' "$*"
}

fail() {
  printf '[test-run][error] %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local pid=""

  if [ -f "$TEST_ROOT/runtime.pids" ]; then
    while read -r pid; do
      [ -n "$pid" ] || continue
      kill -TERM "$pid" >/dev/null 2>&1 || true
    done <"$TEST_ROOT/runtime.pids"
    sleep 1
    while read -r pid; do
      [ -n "$pid" ] || continue
      kill -KILL "$pid" >/dev/null 2>&1 || true
    done <"$TEST_ROOT/runtime.pids"
  fi

  rm -rf "$TEST_ROOT"
}

trap cleanup EXIT

record_pid() {
  printf '%s\n' "$1" >>"$TEST_ROOT/runtime.pids"
}

assert_contains() {
  local file="$1"
  local pattern="$2"

  grep -Fq "$pattern" "$file" || fail "Expected '$pattern' in $file"
}

assert_not_contains() {
  local file="$1"
  local pattern="$2"

  if grep -Fq "$pattern" "$file"; then
    fail "Did not expect '$pattern' in $file"
  fi
}

wait_for_pattern() {
  local file="$1"
  local pattern="$2"
  local timeout_seconds="$3"
  local elapsed=0

  while [ "$elapsed" -lt "$timeout_seconds" ]; do
    if [ -f "$file" ] && grep -Fq "$pattern" "$file"; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  return 1
}

write_sudo_stub() {
  local mode="$1"

  cat >"$STUB_BIN/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mode="${ZEINAGUARD_TEST_SUDO_MODE:-success}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -n|-E|-k)
      if [ "$1" = "-k" ]; then
        exit 0
      fi
      shift
      ;;
    --)
      shift
      break
      ;;
    *)
      break
      ;;
  esac
done

if [ "$mode" = "fail" ]; then
  printf 'sudo: a password is required\n' >&2
  exit 1
fi

[ "$#" -gt 0 ] || exit 0
exec "$@"
EOF
  chmod +x "$STUB_BIN/sudo"
  export ZEINAGUARD_TEST_SUDO_MODE="$mode"
}

write_mock_services() {
  cat >"$TEST_ROOT/mock-backend.sh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
trap 'exit 0' INT TERM
while :; do
  sleep 1
done
EOF
  chmod +x "$TEST_ROOT/mock-backend.sh"

  cat >"$TEST_ROOT/mock-frontend.sh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
trap 'exit 0' INT TERM
while :; do
  sleep 1
done
EOF
  chmod +x "$TEST_ROOT/mock-frontend.sh"

  cat >"$TEST_ROOT/mock-sensor.sh" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
if [ "${1:-}" = "--test" ]; then
  exit 0
fi
if [ "${ZEINAGUARD_SENSOR_CRASH:-0}" = "1" ]; then
  printf 'mock sensor crash\n' >&2
  exit 1
fi
trap 'exit 0' INT TERM
while :; do
  sleep 1
done
EOF
  chmod +x "$TEST_ROOT/mock-sensor.sh"
}

setup_case_env() {
  local case_name="$1"

  export PATH="$STUB_BIN:$PATH_ORIG"
  export ZEINAGUARD_LOG_DIR="$TEST_ROOT/$case_name/logs"
  export SENSOR_INTERFACE="lo"
  export ZEINAGUARD_BACKEND_CMD_OVERRIDE="$TEST_ROOT/mock-backend.sh"
  export ZEINAGUARD_FRONTEND_CMD_OVERRIDE="$TEST_ROOT/mock-frontend.sh"
  export ZEINAGUARD_SENSOR_CMD_OVERRIDE="$TEST_ROOT/mock-sensor.sh"
  export ZEINAGUARD_SKIP_BACKEND_HEALTHCHECK=1
  export ZEINAGUARD_SKIP_FRONTEND_HEALTHCHECK=1
  export ZEINAGUARD_SENSOR_CRASH=0

  mkdir -p "$ZEINAGUARD_LOG_DIR"
}

run_port_conflict_test() {
  local output_file="$ARTIFACT_DIR/port-conflict.out"
  local listener_pid=""
  local unsafe_dir="$TEST_ROOT/unsafe-listener"

  mkdir -p "$unsafe_dir"
  setup_case_env "port-conflict"
  write_sudo_stub success

  (
    cd "$unsafe_dir"
    python3 -m http.server 3000 --bind 127.0.0.1 >"$ARTIFACT_DIR/port-listener.log" 2>&1
  ) &
  listener_pid=$!
  record_pid "$listener_pid"
  sleep 1

  (
    cd "$ROOT_DIR"
    ./run.sh --dry-run
  ) >"$output_file" 2>&1

  assert_contains "$output_file" "Frontend URL: http://127.0.0.1:3001"
  log "Port conflict scenario passed"
}

run_stale_pid_test() {
  local output_file="$ARTIFACT_DIR/stale-pid.out"
  local pid_file=""

  setup_case_env "stale-pid"
  write_sudo_stub success
  pid_file="$ZEINAGUARD_LOG_DIR/zeinaguard.pids"

  cat >"$pid_file" <<'EOF'
backend_pid=999999
backend_pgid=999999
backend_port=5000
frontend_pid=888888
frontend_pgid=888888
frontend_port=3000
sensor_pid=777777
sensor_pgid=777777
sensor_port=n/a
final_backend_port=5000
final_frontend_port=3000
EOF

  (
    cd "$ROOT_DIR"
    ./run.sh --dry-run
  ) >"$output_file" 2>&1

  assert_not_contains "$pid_file" "999999"
  assert_not_contains "$pid_file" "888888"
  assert_not_contains "$pid_file" "777777"
  log "Stale PID scenario passed"
}

run_sudo_failure_test() {
  local output_file="$ARTIFACT_DIR/sudo-failure.out"
  local status=0

  setup_case_env "sudo-failure"
  write_sudo_stub fail

  set +e
  (
    cd "$ROOT_DIR"
    ./run.sh --dry-run
  ) >"$output_file" 2>&1
  status=$?
  set -e

  [ "$status" -ne 0 ] || fail "Expected sudo failure scenario to exit non-zero"
  assert_contains "$output_file" "Sensor requires passwordless sudo (NOPASSWD)"
  log "Sudo failure scenario passed"
}

run_sensor_crash_test() {
  local output_file="$ARTIFACT_DIR/sensor-crash.out"
  local run_pid=""
  local wait_status=0

  setup_case_env "sensor-crash"
  write_sudo_stub success
  export ZEINAGUARD_SENSOR_CRASH=1

  (
    cd "$ROOT_DIR"
    ./run.sh
  ) >"$output_file" 2>&1 &
  run_pid=$!
  record_pid "$run_pid"

  wait_for_pattern "$output_file" "Sensor disabled:" 20 || fail "Sensor crash scenario did not disable the sensor"
  kill -0 "$run_pid" >/dev/null 2>&1 || fail "Supervisor exited after sensor failure; expected degraded mode"
  kill -INT "$run_pid"
  wait "$run_pid" || wait_status=$?
  [ "$wait_status" -eq 0 ] || fail "Supervisor did not exit cleanly after SIGINT in sensor crash scenario"
  log "Sensor crash scenario passed"
}

run_clean_startup_test() {
  local output_file="$ARTIFACT_DIR/clean-startup.out"
  local run_pid=""
  local wait_status=0

  setup_case_env "clean-startup"
  write_sudo_stub success

  (
    cd "$ROOT_DIR"
    ./run.sh
  ) >"$output_file" 2>&1 &
  run_pid=$!
  record_pid "$run_pid"

  wait_for_pattern "$output_file" "ZeinaGuard is running" 20 || fail "Clean startup scenario did not reach running state"
  kill -INT "$run_pid"
  wait "$run_pid" || wait_status=$?
  [ "$wait_status" -eq 0 ] || fail "Supervisor did not exit cleanly after SIGINT in clean startup scenario"
  [ ! -f "$ZEINAGUARD_LOG_DIR/zeinaguard.pids" ] || fail "PID file still exists after clean shutdown"
  log "Clean startup scenario passed"
}

write_mock_services

log "Validating shell syntax"
bash -n "$RUN_SH"
bash -n "$ROOT_DIR/test-run.sh"

run_port_conflict_test
run_stale_pid_test
run_sudo_failure_test
run_sensor_crash_test
run_clean_startup_test

log "All validation scenarios passed"
