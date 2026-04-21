#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
FRONTEND_DIR="$ROOT_DIR"
FRONTEND_RUNTIME_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
SENSOR_DIR="$ROOT_DIR/sensor"
ENV_FILE="$ROOT_DIR/.env"

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-5000}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
BACKEND_VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
SENSOR_VENV_PYTHON="$SENSOR_DIR/.venv/bin/python"

FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/backend.log"
SENSOR_LOG="$LOG_DIR/sensor.log"
SENSOR_TEST_LOG="$LOG_DIR/sensor-preflight.log"

declare -a START_ORDER=()
declare -A SERVICE_PIDS=()
declare -a PREFLIGHT_ERRORS=()
declare -a PREFLIGHT_NOTES=()

CLEANUP_DONE=0
SELECTED_SENSOR_INTERFACE=""

log() {
  printf '[start_smart] %s\n' "$*"
}

warn() {
  printf '[start_smart][warn] %s\n' "$*" >&2
}

fail() {
  printf '[start_smart][error] %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

ensure_command() {
  local command_name="$1"
  command_exists "$command_name" || fail "Required command not found: $command_name"
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
  fi

  BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
  export FLASK_PORT="$BACKEND_PORT"
  export BACKEND_URL="$BACKEND_URL"
  export NEXT_PUBLIC_API_URL="$BACKEND_URL"
  export NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL"
  export ZEINAGUARD_NONINTERACTIVE=1
}

ensure_runtime_dirs() {
  mkdir -p "$LOG_DIR"
}

add_preflight_error() {
  PREFLIGHT_ERRORS+=("$1")
}

add_preflight_note() {
  PREFLIGHT_NOTES+=("$1")
}

require_directory() {
  local path="$1"
  local description="$2"
  [ -d "$path" ] || add_preflight_error "$description is missing: $path"
}

require_file() {
  local path="$1"
  local description="$2"
  [ -f "$path" ] || add_preflight_error "$description is missing: $path"
}

validate_command() {
  local command_name="$1"
  command_exists "$command_name" || add_preflight_error "Required command is not installed: $command_name"
}

validate_venv_python() {
  local service_name="$1"
  local python_bin="$2"

  if [ ! -x "$python_bin" ]; then
    add_preflight_error "${service_name} virtual environment is missing Python: $python_bin"
    return
  fi

  if ! "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    add_preflight_error "${service_name} virtual environment Python is not runnable: $python_bin"
    return
  fi

  "$python_bin" -m pip --version >/dev/null 2>&1 || add_preflight_error "${service_name} virtual environment pip is unavailable"
}

validate_noninteractive_sudo() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    add_preflight_note "Running as root; sudo password prompt is not required"
    return
  fi

  if ! command_exists sudo; then
    add_preflight_error "Required command is not installed: sudo"
    return
  fi

  if sudo -n true >/dev/null 2>&1; then
    add_preflight_note "sudo is available in non-interactive mode"
    return
  fi

  add_preflight_error "sudo requires a password or terminal prompt. Configure NOPASSWD or run as root."
}

interface_exists() {
  local interface_name="$1"

  [ -n "$interface_name" ] || return 1

  if command_exists ip && ip link show "$interface_name" >/dev/null 2>&1; then
    return 0
  fi

  if command_exists iwconfig && iwconfig "$interface_name" >/dev/null 2>&1; then
    return 0
  fi

  return 1
}

discover_wireless_interfaces() {
  local interface_path=""

  if [ -d /sys/class/net ]; then
    for interface_path in /sys/class/net/*; do
      [ -e "$interface_path/wireless" ] || continue
      basename "$interface_path"
    done
    return
  fi

  if command_exists iwconfig; then
    iwconfig 2>/dev/null | awk '/^[[:alnum:]_.:-]+/ && $0 !~ /no wireless extensions/ {print $1}'
  fi
}

select_sensor_interface() {
  local candidate=""
  local discovered_interface=""
  local -a candidates=()
  local -A seen_candidates=()

  if [ -n "${SENSOR_INTERFACE:-}" ]; then
    candidates+=("$SENSOR_INTERFACE")
  fi
  candidates+=("wlan0mon" "wlan0")

  while read -r discovered_interface; do
    [ -n "$discovered_interface" ] || continue
    candidates+=("$discovered_interface")
  done < <(discover_wireless_interfaces)

  for candidate in "${candidates[@]}"; do
    [ -n "$candidate" ] || continue
    if [ -n "${seen_candidates[$candidate]:-}" ]; then
      continue
    fi
    seen_candidates["$candidate"]=1

    if interface_exists "$candidate"; then
      SELECTED_SENSOR_INTERFACE="$candidate"
      export SENSOR_INTERFACE="$candidate"
      return 0
    fi
  done

  return 1
}

print_preflight_failures() {
  local item

  printf '[start_smart][error] Pre-flight validation failed:\n' >&2
  for item in "${PREFLIGHT_ERRORS[@]}"; do
    printf '  - %s\n' "$item" >&2
  done
}

run_preflight_checks() {
  local note=""

  PREFLIGHT_ERRORS=()
  PREFLIGHT_NOTES=()

  log "Running pre-flight validation"

  require_directory "$FRONTEND_RUNTIME_DIR" "Frontend runtime directory"
  require_file "$FRONTEND_DIR/package.json" "Frontend package manifest"
  require_file "$BACKEND_DIR/app.py" "Backend entrypoint"
  require_file "$SENSOR_DIR/main.py" "Sensor entrypoint"

  validate_command python3
  validate_command pnpm
  validate_command setsid
  validate_noninteractive_sudo

  if [ -d "$BACKEND_DIR/.venv" ]; then
    validate_venv_python "backend" "$BACKEND_VENV_PYTHON"
  else
    add_preflight_error "Backend virtual environment is missing: $BACKEND_DIR/.venv"
  fi

  if [ -d "$SENSOR_DIR/.venv" ]; then
    validate_venv_python "sensor" "$SENSOR_VENV_PYTHON"
  else
    add_preflight_error "Sensor virtual environment is missing: $SENSOR_DIR/.venv"
  fi

  if [ -d "$FRONTEND_DIR/node_modules" ]; then
    add_preflight_note "Frontend dependencies already cached in node_modules"
  else
    add_preflight_note "node_modules is missing; pnpm install will run before startup"
  fi

  if ! command_exists ip && ! command_exists iwconfig; then
    add_preflight_error "Cannot validate wireless interfaces because neither ip nor iwconfig is installed"
  elif ! select_sensor_interface; then
    add_preflight_error "No wireless interface detected. Set SENSOR_INTERFACE or attach a wireless interface such as wlan0, wlan0mon, or wlx*"
  else
    add_preflight_note "Using sensor interface: $SELECTED_SENSOR_INTERFACE"
  fi

  if [ "${#PREFLIGHT_ERRORS[@]}" -gt 0 ]; then
    print_preflight_failures
    return 1
  fi

  for note in "${PREFLIGHT_NOTES[@]}"; do
    log "$note"
  done
  log "Pre-flight validation passed"
}

ensure_frontend_dependencies() {
  if [ -d "$FRONTEND_DIR/node_modules" ]; then
    log "Reusing cached frontend dependencies"
    return
  fi

  log "Installing frontend dependencies with pnpm"
  (
    cd "$FRONTEND_DIR"
    pnpm install
  )
}

pid_file_for() {
  printf '%s/%s.pid\n' "$LOG_DIR" "$1"
}

port_listeners() {
  local port="$1"

  if command_exists fuser; then
    fuser -n tcp "$port" 2>/dev/null || sudo -n fuser -n tcp "$port" 2>/dev/null || true
    return
  fi

  if command_exists lsof; then
    lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true
  fi
}

process_running() {
  local pid="$1"
  local state=""

  [ -n "$pid" ] || return 1
  state="$(ps -o stat= -p "$pid" 2>/dev/null | awk 'NR==1 {print $1}')"
  [ -n "$state" ] && [[ "$state" != Z* ]]
}

signal_pid() {
  local signal_name="$1"
  local pid="$2"

  [ -n "$pid" ] || return 0

  if kill "-${signal_name}" "$pid" >/dev/null 2>&1; then
    return 0
  fi

  if command_exists sudo; then
    sudo -n kill "-${signal_name}" "$pid" >/dev/null 2>&1 || true
  fi
}

signal_process_group() {
  local signal_name="$1"
  local pid="$2"

  [ -n "$pid" ] || return 0

  if kill "-${signal_name}" -- "-$pid" >/dev/null 2>&1; then
    return 0
  fi

  if command_exists sudo; then
    sudo -n kill "-${signal_name}" -- "-$pid" >/dev/null 2>&1 || true
  fi
}

wait_for_process_exit() {
  local pid="$1"
  local timeout_seconds="${2:-10}"
  local elapsed=0

  while process_running "$pid" && [ "$elapsed" -lt "$timeout_seconds" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done

  ! process_running "$pid"
}

terminate_pid() {
  local pid="$1"
  local label="$2"

  [ -n "$pid" ] || return 0
  if ! process_running "$pid"; then
    return 0
  fi

  log "Stopping $label (pid $pid)"
  signal_process_group TERM "$pid"
  signal_pid TERM "$pid"

  if wait_for_process_exit "$pid" 10; then
    return 0
  fi

  warn "$label did not stop gracefully; forcing shutdown"
  signal_process_group KILL "$pid"
  signal_pid KILL "$pid"
  wait_for_process_exit "$pid" 5 || true
}

stop_pid_file_if_present() {
  local service_name="$1"
  local pid_file
  local pid=""

  pid_file="$(pid_file_for "$service_name")"
  if [ ! -f "$pid_file" ]; then
    return
  fi

  pid="$(tr -d '[:space:]' <"$pid_file" || true)"
  terminate_pid "$pid" "$service_name"
  rm -f "$pid_file"
}

cleanup_port_if_needed() {
  local port="$1"

  if [ -z "$(port_listeners "$port")" ]; then
    return 0
  fi

  warn "Port $port is busy; attempting cleanup"
  if command_exists fuser; then
    fuser -k -TERM -n tcp "$port" >/dev/null 2>&1 || sudo -n fuser -k -TERM -n tcp "$port" >/dev/null 2>&1 || true
    sleep 2
    if [ -n "$(port_listeners "$port")" ]; then
      fuser -k -KILL -n tcp "$port" >/dev/null 2>&1 || sudo -n fuser -k -KILL -n tcp "$port" >/dev/null 2>&1 || true
      sleep 1
    fi
  elif command_exists lsof; then
    while read -r port_pid; do
      [ -n "$port_pid" ] || continue
      kill -TERM "$port_pid" >/dev/null 2>&1 || true
    done <<<"$(port_listeners "$port")"
    sleep 2
  fi

  [ -z "$(port_listeners "$port")" ] || fail "Port $port is still busy after cleanup"
}

ensure_port_available() {
  local service_name="$1"
  local port="$2"

  stop_pid_file_if_present "$service_name"
  cleanup_port_if_needed "$port"
}

start_service() {
  local service_name="$1"
  local workdir="$2"
  local log_file="$3"
  shift 3

  local pid_file
  local pid

  pid_file="$(pid_file_for "$service_name")"
  : >"$log_file"

  (
    cd "$workdir"
    exec setsid "$@"
  ) >>"$log_file" 2>&1 &

  pid="$!"
  printf '%s\n' "$pid" >"$pid_file"
  SERVICE_PIDS["$service_name"]="$pid"
  START_ORDER+=("$service_name")

  sleep 2
  process_running "$pid" || fail "$service_name failed to start; see $log_file"
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="$2"
  local expected_json_key="${3:-}"
  local expected_json_value="${4:-}"
  local deadline=$((SECONDS + timeout_seconds))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if python3 - "$url" "$expected_json_key" "$expected_json_value" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

url = sys.argv[1]
expected_key = sys.argv[2]
expected_value = sys.argv[3]

try:
    with urllib.request.urlopen(url, timeout=2) as response:
        body = response.read().decode("utf-8", errors="replace")
        if not expected_key:
            raise SystemExit(0 if 200 <= response.status < 300 else 1)
        payload = json.loads(body)
except Exception:
    raise SystemExit(1)

raise SystemExit(0 if str(payload.get(expected_key, "")) == expected_value else 1)
PY
    then
      return 0
    fi
    sleep 2
  done

  return 1
}

wait_for_socketio_endpoint() {
  local timeout_seconds="${1:-30}"
  local deadline=$((SECONDS + timeout_seconds))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if python3 - "$BACKEND_URL" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

base_url = sys.argv[1].rstrip("/")
url = f"{base_url}/socket.io/?transport=polling&EIO=4&t=preflight"

try:
    with urllib.request.urlopen(url, timeout=2) as response:
        body = response.read().decode("utf-8", errors="replace")
except Exception:
    raise SystemExit(1)

raise SystemExit(0 if response.status == 200 and "sid" in body else 1)
PY
    then
      return 0
    fi
    sleep 2
  done

  return 1
}

verify_backend_runtime_readiness() {
  log "Waiting for backend health endpoint on ${BACKEND_URL}"
  wait_for_http "$BACKEND_URL/health" 60 status healthy || fail "Backend health check failed; see $BACKEND_LOG"
  wait_for_http "$BACKEND_URL/ready" 60 ready True || fail "Backend readiness check failed; see $BACKEND_LOG"
  wait_for_socketio_endpoint 30 || fail "Backend Socket.IO endpoint is not ready; see $BACKEND_LOG"
  log "Backend is fully ready"
}

run_sensor_preflight_test() {
  local -a command

  : >"$SENSOR_TEST_LOG"
  log "Running sensor self-test on interface ${SELECTED_SENSOR_INTERFACE}"

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    command=("$SENSOR_VENV_PYTHON" "$SENSOR_DIR/main.py" --test)
  else
    command=(sudo -n -E "$SENSOR_VENV_PYTHON" "$SENSOR_DIR/main.py" --test)
  fi

  if (
    cd "$SENSOR_DIR"
    env BACKEND_URL="$BACKEND_URL" ZEINAGUARD_NONINTERACTIVE=1 SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
      "${command[@]}"
  ) >>"$SENSOR_TEST_LOG" 2>&1; then
    log "Sensor self-test passed"
    return 0
  fi

  fail "Sensor self-test failed; see $SENSOR_TEST_LOG"
}

build_sensor_command() {
  local -n out_command_ref="$1"

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    out_command_ref=("$SENSOR_VENV_PYTHON" "$SENSOR_DIR/main.py")
    return
  fi

  out_command_ref=(sudo -n -E "$SENSOR_VENV_PYTHON" "$SENSOR_DIR/main.py")
}

cleanup_all() {
  local exit_code="${1:-0}"
  local index
  local service_name

  if [ "$CLEANUP_DONE" -eq 1 ]; then
    return
  fi

  CLEANUP_DONE=1

  for ((index=${#START_ORDER[@]} - 1; index>=0; index--)); do
    service_name="${START_ORDER[$index]}"
    stop_pid_file_if_present "$service_name"
  done

  cleanup_port_if_needed "$FRONTEND_PORT" || true
  cleanup_port_if_needed "$BACKEND_PORT" || true
}

on_interrupt() {
  printf '\n'
  log "Interrupt received, shutting down services"
  cleanup_all 0
  exit 0
}

on_exit() {
  local exit_code="$?"
  if [ "$exit_code" -ne 0 ] && [ "${#START_ORDER[@]}" -gt 0 ]; then
    warn "Startup failed; cleaning up running services"
    cleanup_all "$exit_code"
  fi
}

print_summary() {
  cat <<EOF
ZeinaGuard Pro is running
Frontend URL: http://127.0.0.1:${FRONTEND_PORT}
Backend URL : ${BACKEND_URL}
Logs        : ${LOG_DIR}
EOF
}

monitor_services() {
  local service_name
  local pid

  while true; do
    for service_name in "${START_ORDER[@]}"; do
      pid="${SERVICE_PIDS[$service_name]:-}"
      if ! process_running "$pid"; then
        fail "$service_name exited unexpectedly; see $LOG_DIR/$service_name.log"
      fi
    done
    sleep 2
  done
}

main() {
  local -a sensor_command

  trap on_interrupt INT TERM
  trap on_exit EXIT

  ensure_command bash
  load_env_file
  ensure_runtime_dirs
  run_preflight_checks || exit 1

  ensure_frontend_dependencies

  ensure_port_available "backend" "$BACKEND_PORT"
  ensure_port_available "frontend" "$FRONTEND_PORT"
  stop_pid_file_if_present "sensor"

  start_service "backend" "$BACKEND_DIR" "$BACKEND_LOG" \
    env FLASK_PORT="$BACKEND_PORT" BACKEND_URL="$BACKEND_URL" SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
    "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py"
  verify_backend_runtime_readiness

  start_service "frontend" "$FRONTEND_DIR" "$FRONTEND_LOG" \
    env NEXT_PUBLIC_API_URL="$BACKEND_URL" NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL" \
    pnpm dev
  wait_for_http "http://127.0.0.1:${FRONTEND_PORT}" 90 || fail "Frontend failed health check; see $FRONTEND_LOG"

  run_sensor_preflight_test
  build_sensor_command sensor_command

  start_service "sensor" "$SENSOR_DIR" "$SENSOR_LOG" \
    env BACKEND_URL="$BACKEND_URL" ZEINAGUARD_NONINTERACTIVE=1 SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
    "${sensor_command[@]}"

  print_summary
  monitor_services
}

main "$@"
