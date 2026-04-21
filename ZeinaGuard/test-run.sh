#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_SH="$ROOT_DIR/run.sh"
LOCK_FILE="/tmp/zeinaguard.lock"
TEST_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/zeinaguard-fi.XXXXXX")"
ARTIFACT_DIR="$TEST_ROOT/artifacts"
STUB_BIN="$TEST_ROOT/bin"
PATH_ORIG="$PATH"

mkdir -p "$ARTIFACT_DIR" "$STUB_BIN"

declare -a REQUESTED_MODES=()
declare -a TRACKED_PIDS=()

usage() {
  cat <<'EOF'
Usage: ./test-run.sh [--inject-mode MODE]...

Supported modes:
  sudo_fail
  port_block
  zombie_pid
  backend_crash_mid_start
  frontend_crash_mid_start

If no mode is supplied, all modes run in sequence.
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --inject-mode)
        shift
        [ "$#" -gt 0 ] || { printf '[test-run][error] Missing value for --inject-mode\n' >&2; exit 1; }
        REQUESTED_MODES+=("$1")
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        printf '[test-run][error] Unknown argument: %s\n' "$1" >&2
        exit 1
        ;;
    esac
    shift
  done
}

log() {
  printf '[test-run] %s\n' "$*"
}

fail() {
  printf '[test-run][error] %s\n' "$*" >&2
  exit 1
}

record_pid() {
  TRACKED_PIDS+=("$1")
}

cleanup() {
  local pid=""

  for pid in "${TRACKED_PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    kill -TERM "$pid" >/dev/null 2>&1 || true
  done
  sleep 1
  for pid in "${TRACKED_PIDS[@]:-}"; do
    [ -n "$pid" ] || continue
    kill -KILL "$pid" >/dev/null 2>&1 || true
  done

  rm -rf "$TEST_ROOT"
}

trap cleanup EXIT

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

assert_file_missing() {
  [ ! -e "$1" ] || fail "Expected file to be absent: $1"
}

assert_process_alive() {
  kill -0 "$1" >/dev/null 2>&1 || fail "Expected pid $1 to still be alive"
}

assert_no_process_match() {
  local pattern="$1"
  if ps -eo args= 2>/dev/null | grep -F "$pattern" | grep -vq grep; then
    fail "Expected no running process to match: $pattern"
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

make_sudo_stub() {
  cat >"$STUB_BIN/sudo" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
mode="${ZEINAGUARD_TEST_SUDO_MODE:-success}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -n|-E)
      shift
      ;;
    -k)
      exit 0
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
}

write_mock_service() {
  cat >"$TEST_ROOT/mock_service.py" <<'EOF'
#!/usr/bin/env python3
import signal
import sys
import time

mode = sys.argv[1]

stop = False

def handle(*_args):
    global stop
    stop = True

signal.signal(signal.SIGTERM, handle)
signal.signal(signal.SIGINT, handle)

if mode == "crash":
    time.sleep(1)
    sys.exit(1)

while not stop:
    time.sleep(1)
EOF
  chmod +x "$TEST_ROOT/mock_service.py"
}

service_override_command() {
  local service_name="$1"
  local mode="$2"
  local signature=""
  local prefix=""

  case "$service_name" in
    backend)
      signature="$ROOT_DIR/backend/app.py $ROOT_DIR"
      ;;
    frontend)
      signature="$ROOT_DIR/node_modules/.bin/next dev $ROOT_DIR"
      ;;
    sensor)
      signature="$ROOT_DIR/sensor/main.py $ROOT_DIR"
      ;;
    *)
      return 1
      ;;
  esac

  if [ "$service_name" = "sensor" ]; then
    prefix='if [ "${1:-}" = "--test" ]; then exit 0; fi; '
  fi

  printf '%sexec -a %q python3 %q %q "$@"' "$prefix" "$signature" "$TEST_ROOT/mock_service.py" "$mode"
}

setup_case_env() {
  local case_name="$1"

  export PATH="$STUB_BIN:$PATH_ORIG"
  export ZEINAGUARD_LOG_DIR="$TEST_ROOT/$case_name/logs"
  export ZEINAGUARD_SKIP_BACKEND_HEALTHCHECK=1
  export ZEINAGUARD_SKIP_FRONTEND_HEALTHCHECK=1
  export SENSOR_INTERFACE="lo"
  export ZEINAGUARD_TEST_SUDO_MODE="success"
  export ZEINAGUARD_BACKEND_CMD_OVERRIDE="$(service_override_command backend stable)"
  export ZEINAGUARD_FRONTEND_CMD_OVERRIDE="$(service_override_command frontend stable)"
  export ZEINAGUARD_SENSOR_CMD_OVERRIDE="$(service_override_command sensor stable)"

  mkdir -p "$ZEINAGUARD_LOG_DIR"
  rm -f "$LOCK_FILE"
}

start_external_listener() {
  local port="$1"
  local cwd="$2"
  local pid=""

  mkdir -p "$cwd"
  (
    cd "$cwd"
    python3 -m http.server "$port" --bind 127.0.0.1 >"$ARTIFACT_DIR/listener-$port.log" 2>&1
  ) &
  pid=$!
  record_pid "$pid"
  sleep 1
  printf '%s\n' "$pid"
}

run_runsh() {
  local output_file="$1"
  shift

  (
    cd "$ROOT_DIR"
    ./run.sh "$@"
  ) >"$output_file" 2>&1
}

run_runsh_background() {
  local output_file="$1"
  local pid=""
  shift

  (
    cd "$ROOT_DIR"
    ./run.sh "$@"
  ) >"$output_file" 2>&1 &
  pid=$!
  record_pid "$pid"
  printf '%s\n' "$pid"
}

run_sudo_fail() {
  local output_file="$ARTIFACT_DIR/sudo-fail.out"
  local status=0

  setup_case_env "sudo_fail"
  export ZEINAGUARD_TEST_SUDO_MODE="fail"

  set +e
  run_runsh "$output_file" --dry-run
  status=$?
  set -e

  [ "$status" -ne 0 ] || fail "sudo_fail should exit non-zero"
  assert_contains "$output_file" "Sensor requires passwordless sudo (NOPASSWD)"
  assert_file_missing "$LOCK_FILE"
  log "sudo_fail passed"
}

run_port_block() {
  local output_file="$ARTIFACT_DIR/port-block.out"
  local run_pid=""
  local listener_3000=""
  local listener_5000=""
  local wait_status=0

  setup_case_env "port_block"
  listener_3000="$(start_external_listener 3000 "$TEST_ROOT/external-3000")"
  listener_5000="$(start_external_listener 5000 "$TEST_ROOT/external-5000")"

  run_pid="$(run_runsh_background "$output_file")"
  wait_for_pattern "$output_file" "ZeinaGuard is running" 20 || fail "port_block did not reach running state"

  assert_contains "$output_file" "Frontend URL : http://127.0.0.1:3001"
  assert_contains "$output_file" "Backend URL  : http://127.0.0.1:5001"
  assert_process_alive "$listener_3000"
  assert_process_alive "$listener_5000"

  kill -INT "$run_pid"
  wait "$run_pid" || wait_status=$?
  [ "$wait_status" -eq 0 ] || fail "port_block supervisor did not exit cleanly"
  assert_process_alive "$listener_3000"
  assert_process_alive "$listener_5000"
  assert_file_missing "$LOCK_FILE"
  kill -TERM "$listener_3000" "$listener_5000" >/dev/null 2>&1 || true
  log "port_block passed"
}

run_zombie_pid() {
  local output_file="$ARTIFACT_DIR/zombie-pid.out"
  local run_pid=""
  local wait_status=0

  setup_case_env "zombie_pid"
  cat >"$LOCK_FILE" <<EOF
session_uuid=dead-session
start_timestamp=$(date '+%Y-%m-%d %H:%M:%S %z')
backend_port=5000
frontend_port=3000
EOF

  run_pid="$(run_runsh_background "$output_file")"
  wait_for_pattern "$output_file" "ZeinaGuard is running" 20 || fail "zombie_pid did not recover from stale lock"
  assert_not_contains "$output_file" "could not be reconciled safely"

  kill -INT "$run_pid"
  wait "$run_pid" || wait_status=$?
  [ "$wait_status" -eq 0 ] || fail "zombie_pid supervisor did not exit cleanly"
  assert_file_missing "$LOCK_FILE"
  log "zombie_pid passed"
}

run_backend_crash_mid_start() {
  local output_file="$ARTIFACT_DIR/backend-crash.out"
  local status=0

  setup_case_env "backend_crash_mid_start"
  export ZEINAGUARD_BACKEND_CMD_OVERRIDE="$(service_override_command backend crash)"

  set +e
  run_runsh "$output_file"
  status=$?
  set -e

  [ "$status" -ne 0 ] || fail "backend_crash_mid_start should exit non-zero"
  assert_contains "$output_file" "backend failed to stay running"
  assert_not_contains "$output_file" "Starting frontend"
  assert_file_missing "$LOCK_FILE"
  assert_no_process_match "$ROOT_DIR/backend/app.py $ROOT_DIR"
  log "backend_crash_mid_start passed"
}

run_frontend_crash_mid_start() {
  local output_file="$ARTIFACT_DIR/frontend-crash.out"
  local status=0

  setup_case_env "frontend_crash_mid_start"
  export ZEINAGUARD_FRONTEND_CMD_OVERRIDE="$(service_override_command frontend crash)"

  set +e
  run_runsh "$output_file"
  status=$?
  set -e

  [ "$status" -ne 0 ] || fail "frontend_crash_mid_start should exit non-zero"
  assert_contains "$output_file" "frontend failed to stay running"
  assert_file_missing "$LOCK_FILE"
  assert_no_process_match "$ROOT_DIR/backend/app.py $ROOT_DIR"
  assert_no_process_match "$ROOT_DIR/node_modules/.bin/next dev $ROOT_DIR"
  log "frontend_crash_mid_start passed"
}

run_requested_mode() {
  case "$1" in
    sudo_fail) run_sudo_fail ;;
    port_block) run_port_block ;;
    zombie_pid) run_zombie_pid ;;
    backend_crash_mid_start) run_backend_crash_mid_start ;;
    frontend_crash_mid_start) run_frontend_crash_mid_start ;;
    *)
      fail "Unsupported inject mode: $1"
      ;;
  esac
}

main() {
  local mode=""

  [ "$(uname -s)" = "Linux" ] || fail "test-run.sh must be executed on Linux"
  [ ! -e "$LOCK_FILE" ] || fail "Refusing to run fault injection while $LOCK_FILE already exists"

  make_sudo_stub
  write_mock_service

  bash -n "$RUN_SH"
  bash -n "$ROOT_DIR/test-run.sh"

  if [ "${#REQUESTED_MODES[@]}" -eq 0 ]; then
    REQUESTED_MODES=(
      "sudo_fail"
      "port_block"
      "zombie_pid"
      "backend_crash_mid_start"
      "frontend_crash_mid_start"
    )
  fi

  for mode in "${REQUESTED_MODES[@]}"; do
    log "Running injection mode: $mode"
    run_requested_mode "$mode"
  done

  log "All requested injection modes passed"
}

parse_args "$@"
main
