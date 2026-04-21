#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="${TMPDIR:-/tmp}/zeinaguard.pids"
FRONTEND_DIR="$ROOT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
SENSOR_DIR="$ROOT_DIR/sensor"
ENV_FILE="$ROOT_DIR/.env"

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-5000}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${BACKEND_PORT}}"
BACKEND_VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
SENSOR_VENV_PYTHON="$SENSOR_DIR/.venv/bin/python"
SENSOR_MAIN="$SENSOR_DIR/main.py"

FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/backend.log"
SENSOR_LOG="$LOG_DIR/sensor.log"

declare -A SERVICE_PIDS=()
declare -a SERVICE_ORDER=("sensor" "backend" "frontend")
declare -a PREFLIGHT_ERRORS=()
declare -a PREFLIGHT_NOTES=()
declare -a BACKEND_RETRY_DELAYS=(1 1 2 2 3 3 5 5 8 10)

SELECTED_SENSOR_INTERFACE=""
SHUTDOWN_DONE=0

log() {
  printf '[run.sh] %s\n' "$*"
}

warn() {
  printf '[run.sh][warn] %s\n' "$*" >&2
}

fail() {
  printf '[run.sh][error] %s\n' "$*" >&2
  exit 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

current_user() {
  id -un
}

sensor_sudoers_python_rule() {
  printf '%s ALL=(root) NOPASSWD: SETENV: %s %s *' "$(current_user)" "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN"
}

sensor_sudoers_cleanup_rule() {
  local kill_bin="/bin/kill"
  local pkill_bin="${PKILL_BIN:-$(command -v pkill 2>/dev/null || echo /usr/bin/pkill)}"
  printf '%s ALL=(root) NOPASSWD: %s, %s' "$(current_user)" "$kill_bin" "$pkill_bin"
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
  fi

  export FLASK_PORT="$BACKEND_PORT"
  export BACKEND_URL="$BACKEND_URL"
  export NEXT_PUBLIC_API_URL="$BACKEND_URL"
  export NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL"
  export ZEINAGUARD_NONINTERACTIVE=1
  export PYTHONUNBUFFERED=1
}

ensure_runtime_dirs() {
  mkdir -p "$LOG_DIR"
}

reset_runtime_state() {
  rm -f "$PID_FILE"
}

write_pid_file() {
  cat >"$PID_FILE" <<EOF
frontend=${SERVICE_PIDS[frontend]:-}
backend=${SERVICE_PIDS[backend]:-}
sensor=${SERVICE_PIDS[sensor]:-}
EOF
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
  local install_hint="${2:-}"

  if command_exists "$command_name"; then
    return 0
  fi

  if [ -n "$install_hint" ]; then
    add_preflight_error "Required command is not installed: $command_name. $install_hint"
  else
    add_preflight_error "Required command is not installed: $command_name"
  fi
}

ensure_pnpm() {
  if command_exists pnpm; then
    return 0
  fi

  if ! command_exists npm; then
    add_preflight_error "pnpm is missing and npm is unavailable. Install Node.js with npm, then run: npm install -g pnpm"
    return 1
  fi

  log "pnpm not found; attempting automatic install with npm"
  if npm install -g pnpm >/dev/null 2>&1; then
    hash -r
    add_preflight_note "Installed pnpm with npm install -g pnpm"
    return 0
  fi

  if [ -n "${HOME:-}" ]; then
    local user_prefix="$HOME/.local"
    mkdir -p "$user_prefix"
    if npm install -g pnpm --prefix "$user_prefix" >/dev/null 2>&1; then
      export PATH="$user_prefix/bin:$PATH"
      hash -r
      add_preflight_note "Installed pnpm under $user_prefix/bin for the current user"
      return 0
    fi
  fi

  add_preflight_error "pnpm is missing and automatic installation failed. Install it manually with: npm install -g pnpm"
  return 1
}

validate_python_runtime() {
  python3 -m pip --version >/dev/null 2>&1 || add_preflight_error "python3 pip is unavailable. Install it with: sudo apt-get install python3-pip"
  python3 -m venv --help >/dev/null 2>&1 || add_preflight_error "python3 venv support is unavailable. Install it with: sudo apt-get install python3-venv"
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

validate_python_file() {
  local python_bin="$1"
  local path="$2"
  local description="$3"

  "$python_bin" -m py_compile "$path" >/dev/null 2>&1 || add_preflight_error "$description failed Python compilation: $path"
}

port_listeners() {
  local port="$1"

  if command_exists lsof; then
    lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true
    return
  fi

  if command_exists fuser; then
    fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' | awk 'NF'
  fi
}

validate_port_free() {
  local port="$1"
  local listeners=""

  listeners="$(port_listeners "$port")"
  if [ -n "$listeners" ]; then
    add_preflight_error "Port $port is already in use: $listeners"
  fi
}

process_running() {
  local pid="$1"
  local state=""

  [ -n "$pid" ] || return 1
  state="$(ps -o stat= -p "$pid" 2>/dev/null | awk 'NR==1 {print $1}')"
  [ -n "$state" ] && [[ "$state" != Z* ]]
}

process_group_running() {
  local pgid="$1"

  [ -n "$pgid" ] || return 1
  if command_exists pgrep; then
    pgrep -g "$pgid" >/dev/null 2>&1
    return
  fi

  process_running "$pgid"
}

process_group_id() {
  local pid="$1"
  ps -o pgid= -p "$pid" 2>/dev/null | awk 'NR==1 {gsub(/[[:space:]]/, "", $1); print $1}'
}

wait_for_service_exit() {
  local pid="$1"
  local pgid="$2"
  local timeout_seconds="${3:-10}"
  local elapsed=0

  while { process_running "$pid" || process_group_running "$pgid"; } && [ "$elapsed" -lt "$timeout_seconds" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done

  ! process_running "$pid" && ! process_group_running "$pgid"
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
    sleep 1
  done

  return 1
}

wait_for_backend_socketio() {
  local timeout_seconds="$1"
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
    sleep 1
  done

  return 1
}

wait_for_backend_health() {
  local attempt=0
  local delay=0
  local max_attempts="${#BACKEND_RETRY_DELAYS[@]}"

  while [ "$attempt" -lt "$max_attempts" ]; do
    if ! process_running "${SERVICE_PIDS[backend]:-}"; then
      return 1
    fi

    if wait_for_http "$BACKEND_URL/health" 2 status healthy \
      && wait_for_http "$BACKEND_URL/ready" 2 ready True \
      && wait_for_backend_socketio 2; then
      log "Backend health gate passed"
      return 0
    fi

    delay="${BACKEND_RETRY_DELAYS[$attempt]}"
    attempt=$((attempt + 1))
    warn "Backend is not ready yet (attempt ${attempt}/${max_attempts}). Retrying in ${delay}s"
    sleep "$delay"
  done

  return 1
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

run_sensor_command() {
  (
    cd "$SENSOR_DIR"
    BACKEND_URL="$BACKEND_URL" \
    SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
    ZEINAGUARD_NONINTERACTIVE=1 \
    PYTHONUNBUFFERED=1 \
    exec sudo -n \
      --preserve-env=BACKEND_URL,SENSOR_INTERFACE,ZEINAGUARD_NONINTERACTIVE,PYTHONUNBUFFERED \
      "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN" "$@"
  )
}

validate_sensor_sudo() {
  : >"$SENSOR_LOG"

  if run_sensor_command --test 2>&1 | awk -v prefix="[sensor] " '{ print prefix $0; fflush() }' >>"$SENSOR_LOG"; then
    add_preflight_note "Privileged sensor self-test passed"
    return 0
  fi

  add_preflight_error "Sensor privileged self-test failed. See $SENSOR_LOG"
  add_preflight_error "Configure passwordless sudo for sensor startup and shutdown. Suggested sudoers entries:"
  add_preflight_error "  $(sensor_sudoers_python_rule)"
  add_preflight_error "  $(sensor_sudoers_cleanup_rule)"
  return 1
}

terminate_process_group() {
  local service_name="$1"
  local pid="$2"
  local signal_name="$3"
  local pgid="$4"

  [ -n "$pid" ] || return 0
  [ -n "$pgid" ] || pgid="$pid"

  kill "-$signal_name" -- "-$pgid" >/dev/null 2>&1 || true
  kill "-$signal_name" "$pid" >/dev/null 2>&1 || true

  if [ "$service_name" = "sensor" ] && command_exists sudo; then
    sudo -n kill "-$signal_name" -- "-$pgid" >/dev/null 2>&1 || true
    sudo -n kill "-$signal_name" "$pid" >/dev/null 2>&1 || true
    sudo -n pkill "-$signal_name" -f "$SENSOR_MAIN" >/dev/null 2>&1 || true
  fi
}

kill_listeners_on_port() {
  local port="$1"
  local pid=""

  while read -r pid; do
    [ -n "$pid" ] || continue
    kill -TERM "$pid" >/dev/null 2>&1 || sudo -n kill -TERM "$pid" >/dev/null 2>&1 || true
  done < <(port_listeners "$port")

  sleep 2

  while read -r pid; do
    [ -n "$pid" ] || continue
    kill -KILL "$pid" >/dev/null 2>&1 || sudo -n kill -KILL "$pid" >/dev/null 2>&1 || true
  done < <(port_listeners "$port")
}

cleanup_ports() {
  kill_listeners_on_port "$FRONTEND_PORT"
  kill_listeners_on_port "$BACKEND_PORT"
}

start_service() {
  local service_name="$1"
  local workdir="$2"
  local log_file="$3"
  shift 3

  local pid=""

  : >"$log_file"
  (
    cd "$workdir"
    exec setsid bash -lc '
      set -o pipefail
      service_prefix="$1"
      shift
      "$@" 2>&1 | awk -v prefix="[$service_prefix] " '"'"'{ print prefix $0; fflush() }'"'"'
    ' _ "$service_name" "$@"
  ) >>"$log_file" 2>&1 &

  pid="$!"
  SERVICE_PIDS["$service_name"]="$pid"
  write_pid_file

  sleep 2
  process_running "$pid" || fail "$service_name failed to stay running. See $log_file"
}

stop_service() {
  local service_name="$1"
  local pid="${SERVICE_PIDS[$service_name]:-}"
  local pgid=""

  [ -n "$pid" ] || return 0
  pgid="$(process_group_id "$pid")"

  log "Stopping $service_name (pid $pid)"
  terminate_process_group "$service_name" "$pid" TERM "${pgid:-$pid}"

  if wait_for_service_exit "$pid" "${pgid:-$pid}" 10; then
    wait "$pid" 2>/dev/null || true
    SERVICE_PIDS["$service_name"]=""
    write_pid_file
    return 0
  fi

  warn "$service_name did not stop gracefully; forcing shutdown"
  terminate_process_group "$service_name" "$pid" KILL "${pgid:-$pid}"
  wait_for_service_exit "$pid" "${pgid:-$pid}" 5 || true
  wait "$pid" 2>/dev/null || true
  SERVICE_PIDS["$service_name"]=""
  write_pid_file
}

cleanup_child_processes() {
  local child_pid=""

  if command_exists pgrep; then
    while read -r child_pid; do
      [ -n "$child_pid" ] || continue
      kill -TERM "$child_pid" >/dev/null 2>&1 || true
    done < <(pgrep -P "$$" || true)
    sleep 2
    while read -r child_pid; do
      [ -n "$child_pid" ] || continue
      kill -KILL "$child_pid" >/dev/null 2>&1 || true
    done < <(pgrep -P "$$" || true)
  fi
}

shutdown_all() {
  local exit_code="${1:-0}"
  local service_name=""

  if [ "$SHUTDOWN_DONE" -eq 1 ]; then
    return
  fi

  SHUTDOWN_DONE=1

  for service_name in "${SERVICE_ORDER[@]}"; do
    stop_service "$service_name"
  done

  cleanup_child_processes
  cleanup_ports
  rm -f "$PID_FILE"
  wait 2>/dev/null || true

  if [ "$exit_code" -eq 0 ]; then
    log "Shutdown complete"
  fi
}

print_preflight_failures() {
  local item=""

  printf '[run.sh][error] Pre-flight validation failed:\n' >&2
  for item in "${PREFLIGHT_ERRORS[@]}"; do
    printf '  - %s\n' "$item" >&2
  done
}

run_preflight_checks() {
  local note=""

  PREFLIGHT_ERRORS=()
  PREFLIGHT_NOTES=()

  log "Running pre-flight validation"

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    add_preflight_error "Do not run run.sh as root. Run it as your normal user so frontend and backend stay unprivileged."
  fi

  require_directory "$BACKEND_DIR" "Backend directory"
  require_directory "$SENSOR_DIR" "Sensor directory"
  require_file "$FRONTEND_DIR/package.json" "Frontend package manifest"
  require_file "$BACKEND_DIR/app.py" "Backend entrypoint"
  require_file "$SENSOR_MAIN" "Sensor entrypoint"

  validate_command node "Install Node.js first."
  validate_command python3 "Install Python 3 first."
  validate_command sudo "Install sudo and configure non-root access for the sensor."
  validate_command setsid "Install util-linux so the launcher can isolate process groups."

  ensure_pnpm
  validate_python_runtime

  if ! command_exists lsof && ! command_exists fuser; then
    add_preflight_error "Port inspection requires lsof or fuser to be installed"
  fi

  if ! command_exists ip && ! command_exists iwconfig; then
    add_preflight_error "Wireless interface discovery requires iproute2 or wireless-tools"
  fi

  if [ -d "$BACKEND_DIR/.venv" ]; then
    validate_venv_python "backend" "$BACKEND_VENV_PYTHON"
    validate_python_file "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py" "Backend entrypoint"
  else
    add_preflight_error "Backend virtual environment is missing: $BACKEND_DIR/.venv"
  fi

  if [ -d "$SENSOR_DIR/.venv" ]; then
    validate_venv_python "sensor" "$SENSOR_VENV_PYTHON"
    validate_python_file "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN" "Sensor entrypoint"
  else
    add_preflight_error "Sensor virtual environment is missing: $SENSOR_DIR/.venv"
  fi

  if [ -d "$FRONTEND_DIR/node_modules" ]; then
    add_preflight_note "Frontend dependencies already cached in node_modules"
  else
    add_preflight_note "node_modules is missing; pnpm install will run before startup"
  fi

  validate_port_free "$BACKEND_PORT"
  validate_port_free "$FRONTEND_PORT"

  if ! select_sensor_interface; then
    add_preflight_error "No usable wireless interface found. Set SENSOR_INTERFACE or attach a wireless adapter."
  else
    add_preflight_note "Using sensor interface: $SELECTED_SENSOR_INTERFACE"
  fi

  if [ "${#PREFLIGHT_ERRORS[@]}" -eq 0 ]; then
    validate_sensor_sudo
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

print_summary() {
  cat <<EOF
ZeinaGuard is running
Frontend URL: http://127.0.0.1:${FRONTEND_PORT}
Backend URL : ${BACKEND_URL}
Logs        : ${LOG_DIR}
PID file    : ${PID_FILE}
EOF
}

on_interrupt() {
  printf '\n'
  log "Signal received, shutting down"
  shutdown_all 0
  exit 0
}

on_exit() {
  local exit_code="$?"
  if [ "$exit_code" -ne 0 ]; then
    warn "Lifecycle supervisor exiting with failure"
    shutdown_all "$exit_code"
  fi
}

monitor_services() {
  while true; do
    if ! process_running "${SERVICE_PIDS[backend]:-}"; then
      fail "Backend exited unexpectedly. See $BACKEND_LOG"
    fi

    if ! process_running "${SERVICE_PIDS[frontend]:-}"; then
      fail "Frontend exited unexpectedly. See $FRONTEND_LOG"
    fi

    if ! process_running "${SERVICE_PIDS[sensor]:-}"; then
      fail "Sensor exited unexpectedly. See $SENSOR_LOG"
    fi

    sleep 2
  done
}

main() {
  trap on_interrupt INT TERM
  trap on_exit EXIT

  load_env_file
  ensure_runtime_dirs
  reset_runtime_state
  run_preflight_checks || exit 1
  ensure_frontend_dependencies

  log "Starting backend"
  start_service \
    "backend" \
    "$BACKEND_DIR" \
    "$BACKEND_LOG" \
    env FLASK_PORT="$BACKEND_PORT" BACKEND_URL="$BACKEND_URL" "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py"

  wait_for_backend_health || fail "Backend failed health gating. See $BACKEND_LOG"

  log "Starting frontend"
  start_service \
    "frontend" \
    "$FRONTEND_DIR" \
    "$FRONTEND_LOG" \
    env NEXT_PUBLIC_API_URL="$BACKEND_URL" NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL" pnpm dev

  wait_for_http "http://127.0.0.1:${FRONTEND_PORT}" 10 || fail "Frontend failed health check. See $FRONTEND_LOG"

  log "Starting sensor"
  start_service \
    "sensor" \
    "$SENSOR_DIR" \
    "$SENSOR_LOG" \
    env BACKEND_URL="$BACKEND_URL" SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" ZEINAGUARD_NONINTERACTIVE=1 PYTHONUNBUFFERED=1 \
    sudo -n --preserve-env=BACKEND_URL,SENSOR_INTERFACE,ZEINAGUARD_NONINTERACTIVE,PYTHONUNBUFFERED \
    "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN"

  print_summary
  monitor_services
}

main "$@"
