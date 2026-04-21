#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$LOG_DIR/zeinaguard.pids"
FRONTEND_DIR="$ROOT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
SENSOR_DIR="$ROOT_DIR/sensor"
ENV_FILE="$ROOT_DIR/.env"

FRONTEND_REQUESTED_PORT="${FRONTEND_PORT:-3000}"
BACKEND_REQUESTED_PORT="${BACKEND_PORT:-5000}"
FRONTEND_PORT_MAX_ATTEMPTS="${FRONTEND_PORT_MAX_ATTEMPTS:-4}"
BACKEND_PORT_MAX_ATTEMPTS="${BACKEND_PORT_MAX_ATTEMPTS:-4}"

FINAL_FRONTEND_PORT=""
FINAL_BACKEND_PORT=""
BACKEND_URL=""

BACKEND_VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
SENSOR_VENV_PYTHON="$SENSOR_DIR/.venv/bin/python"
SENSOR_MAIN="$SENSOR_DIR/main.py"

FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/backend.log"
SENSOR_LOG="$LOG_DIR/sensor.log"

declare -A SERVICE_PID=(
  [backend]=""
  [frontend]=""
  [sensor]=""
)
declare -A SERVICE_PGID=(
  [backend]=""
  [frontend]=""
  [sensor]=""
)
declare -A SERVICE_PORT=(
  [backend]=""
  [frontend]=""
  [sensor]="n/a"
)
declare -A SERVICE_LOG=(
  [backend]="$BACKEND_LOG"
  [frontend]="$FRONTEND_LOG"
  [sensor]="$SENSOR_LOG"
)
declare -A SERVICE_STATE=(
  [backend]="stopped"
  [frontend]="stopped"
  [sensor]="stopped"
)

declare -a SHUTDOWN_ORDER=("sensor" "frontend" "backend")
declare -a PREFLIGHT_ERRORS=()
declare -a PREFLIGHT_NOTES=()
declare -a BACKEND_RETRY_DELAYS=(1 1 2 2 3 3 5 5 8 10)

SELECTED_SENSOR_INTERFACE=""
SENSOR_RESTART_COUNT=0
SENSOR_MAX_RESTARTS=1
SENSOR_DISABLED=0
SHUTDOWN_DONE=0
INTERRUPTED=0

timestamp() {
  date '+%Y-%m-%d %H:%M:%S %z'
}

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

compact_text() {
  printf '%s' "$*" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'
}

current_user() {
  id -un
}

record_service_event() {
  local service_name="$1"
  local event_name="$2"
  local reason="${3:-}"
  local pid_override="${4:-${SERVICE_PID[$service_name]:-}}"
  local port_override="${5:-${SERVICE_PORT[$service_name]:-n/a}}"
  local log_file="${SERVICE_LOG[$service_name]}"
  local message=""

  message="ts=\"$(timestamp)\" service=${service_name} event=${event_name} pid=${pid_override:-none} port=${port_override:-n/a}"
  if [ -n "$reason" ]; then
    message="${message} reason=\"$(compact_text "$reason")\""
  fi

  printf '%s\n' "$message" >>"$log_file"
}

ensure_runtime_dirs() {
  mkdir -p "$LOG_DIR"
}

prepare_log_files() {
  touch "$FRONTEND_LOG" "$BACKEND_LOG" "$SENSOR_LOG"
  printf '%s %s\n' "$(timestamp)" "----- ZeinaGuard session starting -----" >>"$FRONTEND_LOG"
  printf '%s %s\n' "$(timestamp)" "----- ZeinaGuard session starting -----" >>"$BACKEND_LOG"
  printf '%s %s\n' "$(timestamp)" "----- ZeinaGuard session starting -----" >>"$SENSOR_LOG"
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
  fi

  export ZEINAGUARD_NONINTERACTIVE=1
  export PYTHONUNBUFFERED=1
}

refresh_runtime_environment() {
  BACKEND_URL="http://127.0.0.1:${FINAL_BACKEND_PORT}"

  export FINAL_FRONTEND_PORT
  export FINAL_BACKEND_PORT
  export FRONTEND_PORT="$FINAL_FRONTEND_PORT"
  export BACKEND_PORT="$FINAL_BACKEND_PORT"
  export FLASK_PORT="$FINAL_BACKEND_PORT"
  export PORT="$FINAL_FRONTEND_PORT"
  export BACKEND_URL
  export NEXT_PUBLIC_API_URL="$BACKEND_URL"
  export NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL"
  export ZEINAGUARD_NONINTERACTIVE=1
  export PYTHONUNBUFFERED=1

  SERVICE_PORT[backend]="$FINAL_BACKEND_PORT"
  SERVICE_PORT[frontend]="$FINAL_FRONTEND_PORT"
  SERVICE_PORT[sensor]="n/a"
}

clear_service_state() {
  local service_name="$1"
  SERVICE_PID["$service_name"]=""
  SERVICE_PGID["$service_name"]=""
  if [ "$service_name" = "sensor" ]; then
    SERVICE_PORT["$service_name"]="n/a"
  else
    SERVICE_PORT["$service_name"]=""
  fi
  SERVICE_STATE["$service_name"]="stopped"
}

write_pid_file() {
  cat >"$PID_FILE" <<EOF
backend_pid=${SERVICE_PID[backend]:-}
backend_pgid=${SERVICE_PGID[backend]:-}
backend_port=${SERVICE_PORT[backend]:-}
frontend_pid=${SERVICE_PID[frontend]:-}
frontend_pgid=${SERVICE_PGID[frontend]:-}
frontend_port=${SERVICE_PORT[frontend]:-}
sensor_pid=${SERVICE_PID[sensor]:-}
sensor_pgid=${SERVICE_PGID[sensor]:-}
sensor_port=${SERVICE_PORT[sensor]:-}
final_backend_port=${FINAL_BACKEND_PORT:-}
final_frontend_port=${FINAL_FRONTEND_PORT:-}
EOF
}

pid_is_alive() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 1
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

pid_cmdline() {
  local pid="$1"
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\0' ' ' <"/proc/$pid/cmdline" | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'
}

pid_environ_has() {
  local pid="$1"
  local expected="$2"
  [ -r "/proc/$pid/environ" ] || return 1
  tr '\0' '\n' <"/proc/$pid/environ" | grep -Fxq "$expected"
}

pid_cwd() {
  local pid="$1"
  [ -L "/proc/$pid/cwd" ] || return 1
  readlink -f "/proc/$pid/cwd" 2>/dev/null || true
}

pid_owner() {
  local pid="$1"
  ps -o user= -p "$pid" 2>/dev/null | awk 'NR==1 {gsub(/^[[:space:]]+|[[:space:]]+$/, "", $0); print $0}'
}

pid_group() {
  local pid="$1"
  ps -o pgid= -p "$pid" 2>/dev/null | awk 'NR==1 {gsub(/[[:space:]]/, "", $1); print $1}'
}

pid_belongs_to_repo() {
  local pid="$1"
  local cwd=""
  local cmdline=""

  cwd="$(pid_cwd "$pid" || true)"
  if [ -n "$cwd" ] && [[ "$cwd" == "$ROOT_DIR"* ]]; then
    return 0
  fi

  cmdline="$(pid_cmdline "$pid" || true)"
  [ -n "$cmdline" ] && [[ "$cmdline" == *"$ROOT_DIR"* ]]
}

pid_matches_service() {
  local pid="$1"
  local service_name="$2"
  local cmdline=""

  pid_is_alive "$pid" || return 1

  if pid_environ_has "$pid" "ZEINAGUARD_SERVICE=$service_name"; then
    return 0
  fi

  cmdline="$(pid_cmdline "$pid" || true)"
  case "$service_name" in
    backend)
      [[ "$cmdline" == *"$BACKEND_DIR/app.py"* ]]
      ;;
    frontend)
      [[ "$cmdline" == *"pnpm dev"* ]] || [[ "$cmdline" == *"next dev"* ]]
      ;;
    sensor)
      [[ "$cmdline" == *"$SENSOR_MAIN"* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

service_is_running() {
  local service_name="$1"
  local pid="${SERVICE_PID[$service_name]:-}"

  pid_is_alive "$pid" || return 1
  pid_matches_service "$pid" "$service_name"
}

remove_stale_runtime_state() {
  local changed=0
  local service_name=""
  local pid=""

  for service_name in backend frontend sensor; do
    pid="${SERVICE_PID[$service_name]:-}"
    if [ -z "$pid" ]; then
      continue
    fi

    if ! pid_is_alive "$pid" || ! pid_matches_service "$pid" "$service_name"; then
      clear_service_state "$service_name"
      changed=1
    fi
  done

  if [ "$changed" -eq 1 ]; then
    write_pid_file
  fi
}

load_pid_file() {
  local key=""
  local value=""

  clear_service_state backend
  clear_service_state frontend
  clear_service_state sensor

  [ -f "$PID_FILE" ] || return 0

  while IFS='=' read -r key value; do
    case "$key" in
      backend_pid) SERVICE_PID[backend]="$value" ;;
      backend_pgid) SERVICE_PGID[backend]="$value" ;;
      backend_port) SERVICE_PORT[backend]="$value" ;;
      frontend_pid) SERVICE_PID[frontend]="$value" ;;
      frontend_pgid) SERVICE_PGID[frontend]="$value" ;;
      frontend_port) SERVICE_PORT[frontend]="$value" ;;
      sensor_pid) SERVICE_PID[sensor]="$value" ;;
      sensor_pgid) SERVICE_PGID[sensor]="$value" ;;
      sensor_port) SERVICE_PORT[sensor]="$value" ;;
      final_backend_port) FINAL_BACKEND_PORT="$value" ;;
      final_frontend_port) FINAL_FRONTEND_PORT="$value" ;;
    esac
  done <"$PID_FILE"

  remove_stale_runtime_state
}

wait_for_pid_exit() {
  local pid="$1"
  local timeout_seconds="${2:-10}"
  local elapsed=0

  while pid_is_alive "$pid" && [ "$elapsed" -lt "$timeout_seconds" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done

  ! pid_is_alive "$pid"
}

terminate_pid_and_group() {
  local pid="$1"
  local pgid="$2"
  local signal_name="$3"
  local use_sudo="${4:-0}"

  [ -n "$pid" ] || return 0

  if [ -n "$pgid" ]; then
    kill "-$signal_name" -- "-$pgid" >/dev/null 2>&1 || true
    if [ "$use_sudo" -eq 1 ]; then
      sudo -n kill "-$signal_name" -- "-$pgid" >/dev/null 2>&1 || true
    fi
  fi

  kill "-$signal_name" "$pid" >/dev/null 2>&1 || true
  if [ "$use_sudo" -eq 1 ]; then
    sudo -n kill "-$signal_name" "$pid" >/dev/null 2>&1 || true
  fi
}

stop_service() {
  local service_name="$1"
  local reason="${2:-supervisor shutdown}"
  local pid="${SERVICE_PID[$service_name]:-}"
  local pgid="${SERVICE_PGID[$service_name]:-}"
  local service_port="${SERVICE_PORT[$service_name]:-n/a}"
  local use_sudo=0

  if [ -z "$pid" ]; then
    clear_service_state "$service_name"
    write_pid_file
    return 0
  fi

  if ! pid_is_alive "$pid"; then
    clear_service_state "$service_name"
    write_pid_file
    return 0
  fi

  if ! pid_matches_service "$pid" "$service_name"; then
    clear_service_state "$service_name"
    write_pid_file
    return 0
  fi

  if [ -z "$pgid" ]; then
    pgid="$(pid_group "$pid" || true)"
  fi

  if [ "$service_name" = "sensor" ]; then
    use_sudo=1
  fi

  SERVICE_STATE["$service_name"]="stopping"
  record_service_event "$service_name" "stop-requested" "$reason" "$pid" "$service_port"
  terminate_pid_and_group "$pid" "$pgid" TERM "$use_sudo"

  if ! wait_for_pid_exit "$pid" 10; then
    record_service_event "$service_name" "stop-escalated" "TERM timeout, sending KILL" "$pid" "$service_port"
    terminate_pid_and_group "$pid" "$pgid" KILL "$use_sudo"
    wait_for_pid_exit "$pid" 5 || true
  fi

  wait "$pid" 2>/dev/null || true
  clear_service_state "$service_name"
  write_pid_file
  record_service_event "$service_name" "stopped" "$reason" "none" "$service_port"
}

stop_previous_runtime() {
  local live_found=0
  local service_name=""

  [ -f "$PID_FILE" ] || return 0
  load_pid_file

  for service_name in "${SHUTDOWN_ORDER[@]}"; do
    if service_is_running "$service_name"; then
      live_found=1
      break
    fi
  done

  if [ "$live_found" -eq 1 ]; then
    log "Found an existing ZeinaGuard runtime; stopping tracked services safely"
    for service_name in "${SHUTDOWN_ORDER[@]}"; do
      stop_service "$service_name" "pre-start cleanup"
    done
  else
    rm -f "$PID_FILE"
  fi
}

port_has_listener() {
  local port="$1"
  ss -ltnH "( sport = :$port )" 2>/dev/null | grep -q .
}

listener_pids_for_port() {
  local port="$1"
  ss -ltnpH "( sport = :$port )" 2>/dev/null | grep -o 'pid=[0-9]\+' | cut -d= -f2 | sort -u || true
}

listener_is_safe_to_reclaim() {
  local pid="$1"
  local owner=""

  pid_is_alive "$pid" || return 1

  owner="$(pid_owner "$pid" || true)"
  [ -n "$owner" ] || return 1
  [ "$owner" = "$(current_user)" ] || return 1

  pid_belongs_to_repo "$pid"
}

reclaim_listener_pid() {
  local pid="$1"
  local pgid=""

  pgid="$(pid_group "$pid" || true)"
  terminate_pid_and_group "$pid" "$pgid" TERM 0
  if ! wait_for_pid_exit "$pid" 5; then
    terminate_pid_and_group "$pid" "$pgid" KILL 0
    wait_for_pid_exit "$pid" 3 || true
  fi
}

add_preflight_error() {
  PREFLIGHT_ERRORS+=("$1")
}

add_preflight_note() {
  PREFLIGHT_NOTES+=("$1")
}

resolve_port() {
  local service_label="$1"
  local requested_port="$2"
  local max_attempts="$3"
  local target_var="$4"
  local attempt=0
  local candidate=""
  local pids=""
  local pid=""

  while [ "$attempt" -lt "$max_attempts" ]; do
    candidate=$((requested_port + attempt))

    if ! port_has_listener "$candidate"; then
      printf -v "$target_var" '%s' "$candidate"
      add_preflight_note "${service_label} port selected: $candidate"
      return 0
    fi

    pids="$(listener_pids_for_port "$candidate")"
    if [ -n "$pids" ]; then
      local reclaimable=1
      while read -r pid; do
        [ -n "$pid" ] || continue
        if ! listener_is_safe_to_reclaim "$pid"; then
          reclaimable=0
          break
        fi
      done <<<"$pids"

      if [ "$reclaimable" -eq 1 ]; then
        warn "${service_label} port $candidate is busy with a previous ZeinaGuard-owned listener; attempting safe cleanup"
        while read -r pid; do
          [ -n "$pid" ] || continue
          reclaim_listener_pid "$pid"
        done <<<"$pids"

        if ! port_has_listener "$candidate"; then
          printf -v "$target_var" '%s' "$candidate"
          add_preflight_note "Recovered ${service_label} port $candidate by stopping a previous local listener"
          return 0
        fi
      else
        warn "${service_label} port $candidate is busy with a non-reclaimable listener; falling back"
      fi
    else
      warn "${service_label} port $candidate is busy but the owning process is not safely inspectable; falling back"
    fi

    attempt=$((attempt + 1))
  done

  add_preflight_error "Unable to allocate a free ${service_label} port after ${max_attempts} attempts starting at ${requested_port}"
  return 1
}

resolve_runtime_ports() {
  resolve_port "Backend" "$BACKEND_REQUESTED_PORT" "$BACKEND_PORT_MAX_ATTEMPTS" FINAL_BACKEND_PORT || return 1
  resolve_port "Frontend" "$FRONTEND_REQUESTED_PORT" "$FRONTEND_PORT_MAX_ATTEMPTS" FINAL_FRONTEND_PORT || return 1
  refresh_runtime_environment
  write_pid_file
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
url = f"{base_url}/socket.io/?transport=polling&EIO=4&t=supervisor"

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
  local max_attempts="${#BACKEND_RETRY_DELAYS[@]}"
  local delay=0

  while [ "$attempt" -lt "$max_attempts" ]; do
    if ! service_is_running backend; then
      return 1
    fi

    if wait_for_http "$BACKEND_URL/health" 2 status healthy \
      && wait_for_http "$BACKEND_URL/ready" 2 ready True \
      && wait_for_backend_socketio 2; then
      record_service_event "backend" "health-passed" "backend passed health gates"
      log "Backend health gate passed"
      return 0
    fi

    delay="${BACKEND_RETRY_DELAYS[$attempt]}"
    attempt=$((attempt + 1))
    warn "Backend health gate pending (${attempt}/${max_attempts}); retrying in ${delay}s"
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
  local discovered=""
  local -a candidates=()
  declare -A seen=()

  if [ -n "${SENSOR_INTERFACE:-}" ]; then
    candidates+=("$SENSOR_INTERFACE")
  fi
  candidates+=("wlan0mon" "wlan0")

  while read -r discovered; do
    [ -n "$discovered" ] || continue
    candidates+=("$discovered")
  done < <(discover_wireless_interfaces)

  for candidate in "${candidates[@]}"; do
    [ -n "$candidate" ] || continue
    if [ -n "${seen[$candidate]:-}" ]; then
      continue
    fi
    seen["$candidate"]=1

    if interface_exists "$candidate"; then
      SELECTED_SENSOR_INTERFACE="$candidate"
      export SENSOR_INTERFACE="$candidate"
      return 0
    fi
  done

  return 1
}

sensor_sudoers_python_rule() {
  printf '%s ALL=(root) NOPASSWD: SETENV: %s %s *' "$(current_user)" "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN"
}

run_sensor_command() {
  (
    cd "$SENSOR_DIR"
    BACKEND_URL="$BACKEND_URL" \
    SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
    ZEINAGUARD_NONINTERACTIVE=1 \
    PYTHONUNBUFFERED=1 \
    SENSOR_LOG_FILE="$SENSOR_LOG" \
    exec sudo -n -E "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN" "$@"
  )
}

validate_sensor_sudo() {
  local output=""
  local compact_output=""

  sudo -k >/dev/null 2>&1 || true
  if ! sudo -n true >/dev/null 2>&1; then
    add_preflight_error "Sensor requires passwordless sudo (NOPASSWD) to run safely"
    add_preflight_error "Configure non-interactive sudo before starting ZeinaGuard."
    add_preflight_error "Suggested sudoers entry: $(sensor_sudoers_python_rule)"
    return 1
  fi

  record_service_event "sensor" "sudo-validation" "running privileged sensor self-test" "preflight"
  if output="$(run_sensor_command --test 2>&1)"; then
    if [ -n "$output" ]; then
      printf '%s\n' "$output" | awk -v prefix="[sensor] " '{ print prefix $0; fflush() }' >>"$SENSOR_LOG"
    fi
    add_preflight_note "Privileged sensor self-test passed"
    return 0
  fi

  if [ -n "$output" ]; then
    printf '%s\n' "$output" | awk -v prefix="[sensor] " '{ print prefix $0; fflush() }' >>"$SENSOR_LOG"
  fi

  compact_output="$(compact_text "$output")"
  if printf '%s' "$output" | grep -qi 'password .*required'; then
    add_preflight_error "Sensor requires passwordless sudo (NOPASSWD) to run safely"
  else
    add_preflight_error "Sensor privileged self-test failed. See $SENSOR_LOG"
  fi
  [ -n "$compact_output" ] && add_preflight_error "Sensor sudo validation output: $compact_output"
  return 1
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
  validate_command setsid "Install util-linux so services can be isolated in their own process groups."
  validate_command ss "Install iproute2 so port recovery can inspect listeners."
  validate_command ps "Install procps so the supervisor can verify PID ownership."
  validate_command readlink "Install coreutils so the supervisor can verify runtime directories."

  ensure_pnpm || true
  validate_python_runtime

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

  if [ "${#PREFLIGHT_ERRORS[@]}" -eq 0 ]; then
    if ! select_sensor_interface; then
      add_preflight_error "No usable wireless interface found. Set SENSOR_INTERFACE or attach a wireless adapter."
    else
      add_preflight_note "Using sensor interface: $SELECTED_SENSOR_INTERFACE"
    fi
  fi

  if [ "${#PREFLIGHT_ERRORS[@]}" -eq 0 ]; then
    validate_sensor_sudo || true
  fi

  if [ "${#PREFLIGHT_ERRORS[@]}" -gt 0 ]; then
    print_preflight_failures
    return 1
  fi

  for note in "${PREFLIGHT_NOTES[@]}"; do
    log "$note"
  done
  log "Pre-flight validation passed"
  return 0
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

recent_log_excerpt() {
  local log_file="$1"
  local lines="${2:-20}"

  [ -f "$log_file" ] || return 0
  tail -n "$lines" "$log_file" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'
}

start_service() {
  local service_name="$1"
  local workdir="$2"
  local log_file="$3"
  local service_port="$4"
  shift 4

  local pid=""
  local pgid=""
  local failure_reason=""

  SERVICE_PORT["$service_name"]="$service_port"
  SERVICE_STATE["$service_name"]="starting"
  record_service_event "$service_name" "start-requested" "launching service" "pending" "$service_port"

  (
    cd "$workdir"
    exec setsid env ZEINAGUARD_SERVICE="$service_name" bash -lc '
      set -o pipefail
      service_label="$1"
      shift
      "$@" 2>&1 | awk -v prefix="[""$service_label""] " '"'"'{ print prefix $0; fflush() }'"'"'
    ' _ "$service_name" "$@"
  ) >>"$log_file" 2>&1 &

  pid="$!"
  pgid="$(pid_group "$pid" || true)"
  SERVICE_PID["$service_name"]="$pid"
  SERVICE_PGID["$service_name"]="${pgid:-$pid}"
  SERVICE_STATE["$service_name"]="running"
  write_pid_file

  record_service_event "$service_name" "started" "process launched" "$pid" "$service_port"
  log "Started $service_name (pid $pid, port $service_port)"

  sleep 2
  if service_is_running "$service_name"; then
    return 0
  fi

  failure_reason="$(recent_log_excerpt "$log_file" 40)"
  record_service_event "$service_name" "startup-failed" "${failure_reason:-failed to stay running}" "$pid" "$service_port"
  clear_service_state "$service_name"
  write_pid_file
  return 1
}

launch_backend() {
  start_service \
    "backend" \
    "$BACKEND_DIR" \
    "$BACKEND_LOG" \
    "$FINAL_BACKEND_PORT" \
    env FLASK_PORT="$FINAL_BACKEND_PORT" BACKEND_URL="$BACKEND_URL" ZEINAGUARD_NONINTERACTIVE=1 PYTHONUNBUFFERED=1 "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py"
}

launch_frontend() {
  start_service \
    "frontend" \
    "$FRONTEND_DIR" \
    "$FRONTEND_LOG" \
    "$FINAL_FRONTEND_PORT" \
    env PORT="$FINAL_FRONTEND_PORT" NEXT_PUBLIC_API_URL="$BACKEND_URL" NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL" ZEINAGUARD_NONINTERACTIVE=1 pnpm dev -- --port "$FINAL_FRONTEND_PORT"
}

launch_sensor_once() {
  start_service \
    "sensor" \
    "$SENSOR_DIR" \
    "$SENSOR_LOG" \
    "n/a" \
    env BACKEND_URL="$BACKEND_URL" SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" ZEINAGUARD_NONINTERACTIVE=1 PYTHONUNBUFFERED=1 SENSOR_LOG_FILE="$SENSOR_LOG" sudo -n -E "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN"
}

disable_sensor() {
  local reason="$1"
  SENSOR_DISABLED=1
  stop_service "sensor" "$reason"
  record_service_event "sensor" "disabled" "$reason" "none" "n/a"
  warn "Sensor disabled: $reason"
}

start_sensor_service() {
  local startup_reason=""

  if [ "$SENSOR_DISABLED" -eq 1 ]; then
    return 0
  fi

  if launch_sensor_once; then
    return 0
  fi

  startup_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
  record_service_event "sensor" "startup-failed" "${startup_reason:-unknown}"

  if [ "$SENSOR_RESTART_COUNT" -lt "$SENSOR_MAX_RESTARTS" ]; then
    SENSOR_RESTART_COUNT=$((SENSOR_RESTART_COUNT + 1))
    warn "Sensor exited during startup. Restarting once (${SENSOR_RESTART_COUNT}/${SENSOR_MAX_RESTARTS}). Reason: ${startup_reason:-unknown}"
    sleep 2
    if launch_sensor_once; then
      return 0
    fi
    startup_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
    record_service_event "sensor" "startup-retry-failed" "${startup_reason:-unknown}"
  fi

  disable_sensor "sensor failed to stay running after $((SENSOR_RESTART_COUNT + 1)) attempts: ${startup_reason:-unknown}"
  return 0
}

print_summary() {
  local sensor_status="active"

  if [ "$SENSOR_DISABLED" -eq 1 ]; then
    sensor_status="disabled"
  fi

  cat <<EOF
ZeinaGuard is running
Frontend URL: http://127.0.0.1:${FINAL_FRONTEND_PORT}
Backend URL : ${BACKEND_URL}
Sensor      : ${sensor_status}
Logs        : ${LOG_DIR}
PID file    : ${PID_FILE}
EOF
}

shutdown_all() {
  local exit_code="${1:-0}"
  local service_name=""

  if [ "$SHUTDOWN_DONE" -eq 1 ]; then
    return
  fi
  SHUTDOWN_DONE=1

  for service_name in "${SHUTDOWN_ORDER[@]}"; do
    stop_service "$service_name" "supervisor shutdown"
  done

  rm -f "$PID_FILE"

  if [ "$exit_code" -eq 0 ]; then
    log "Shutdown complete"
  fi
}

on_interrupt() {
  INTERRUPTED=1
  printf '\n'
  log "Signal received, shutting down"
  shutdown_all 0
  trap - EXIT
  exit 0
}

on_exit() {
  local exit_code="$?"

  if [ "$SHUTDOWN_DONE" -eq 1 ]; then
    return
  fi

  if [ "$INTERRUPTED" -eq 0 ] && [ "$exit_code" -ne 0 ]; then
    warn "Lifecycle supervisor exiting with failure"
  fi

  shutdown_all "$exit_code"
}

monitor_services() {
  local failure_reason=""

  while true; do
    if ! service_is_running backend; then
      failure_reason="$(recent_log_excerpt "$BACKEND_LOG" 40)"
      record_service_event "backend" "unexpected-exit" "${failure_reason:-unknown}"
      fail "Backend exited unexpectedly. Reason: ${failure_reason:-unknown}. See $BACKEND_LOG"
    fi

    if ! service_is_running frontend; then
      failure_reason="$(recent_log_excerpt "$FRONTEND_LOG" 40)"
      record_service_event "frontend" "unexpected-exit" "${failure_reason:-unknown}"
      fail "Frontend exited unexpectedly. Reason: ${failure_reason:-unknown}. See $FRONTEND_LOG"
    fi

    if [ "$SENSOR_DISABLED" -eq 0 ] && [ -n "${SERVICE_PID[sensor]:-}" ] && ! service_is_running sensor; then
      failure_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
      record_service_event "sensor" "unexpected-exit" "${failure_reason:-unknown}"

      if [ "$SENSOR_RESTART_COUNT" -lt "$SENSOR_MAX_RESTARTS" ]; then
        SENSOR_RESTART_COUNT=$((SENSOR_RESTART_COUNT + 1))
        warn "Sensor exited unexpectedly. Restarting once (${SENSOR_RESTART_COUNT}/${SENSOR_MAX_RESTARTS}). Reason: ${failure_reason:-unknown}"
        stop_service "sensor" "sensor restart requested"
        sleep 2
        if launch_sensor_once; then
          continue
        fi
        failure_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
        record_service_event "sensor" "restart-failed" "${failure_reason:-unknown}"
      fi

      disable_sensor "sensor stopped after retry exhaustion: ${failure_reason:-unknown}"
    fi

    sleep 2
  done
}

main() {
  trap on_interrupt INT TERM
  trap on_exit EXIT

  load_env_file
  ensure_runtime_dirs
  prepare_log_files
  run_preflight_checks || exit 1

  stop_previous_runtime
  resolve_runtime_ports || exit 1
  ensure_frontend_dependencies

  log "Starting backend on port $FINAL_BACKEND_PORT"
  launch_backend || fail "backend failed to stay running. See $BACKEND_LOG"

  wait_for_backend_health || fail "Backend failed health gating. See $BACKEND_LOG"

  log "Starting frontend on port $FINAL_FRONTEND_PORT"
  launch_frontend || fail "frontend failed to stay running. See $FRONTEND_LOG"

  wait_for_http "http://127.0.0.1:${FINAL_FRONTEND_PORT}" 20 || fail "Frontend failed health check. See $FRONTEND_LOG"
  record_service_event "frontend" "health-passed" "frontend HTTP gate passed"

  log "Starting sensor"
  start_sensor_service

  print_summary
  monitor_services
}

main "$@"
