#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${ZEINAGUARD_LOG_DIR:-$ROOT_DIR/logs}"
LOCK_FILE="/tmp/zeinaguard.lock"
FRONTEND_DIR="$ROOT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
SENSOR_DIR="$ROOT_DIR/sensor"
ENV_FILE="$ROOT_DIR/.env"

FRONTEND_REQUESTED_PORT="${FRONTEND_PORT:-3000}"
BACKEND_REQUESTED_PORT="${BACKEND_PORT:-5000}"
FRONTEND_PORT_MAX_ATTEMPTS="${FRONTEND_PORT_MAX_ATTEMPTS:-4}"
BACKEND_PORT_MAX_ATTEMPTS="${BACKEND_PORT_MAX_ATTEMPTS:-4}"

BACKEND_VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
SENSOR_VENV_PYTHON="$SENSOR_DIR/.venv/bin/python"
SENSOR_MAIN="$SENSOR_DIR/main.py"
FRONTEND_NEXT_BIN="$ROOT_DIR/node_modules/.bin/next"

FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/backend.log"
SENSOR_LOG="$LOG_DIR/sensor.log"

declare -A SERVICE_LOG=(
  [backend]="$BACKEND_LOG"
  [frontend]="$FRONTEND_LOG"
  [sensor]="$SENSOR_LOG"
)
declare -A SERVICE_PORT=(
  [backend]=""
  [frontend]=""
  [sensor]="n/a"
)
declare -A SERVICE_RUNTIME_PID=(
  [backend]=""
  [frontend]=""
  [sensor]=""
)
declare -A SERVICE_RETRY=(
  [backend]=0
  [frontend]=0
  [sensor]=0
)

FINAL_FRONTEND_PORT=""
FINAL_BACKEND_PORT=""
BACKEND_URL=""
SELECTED_SENSOR_INTERFACE=""

SESSION_UUID=""
SESSION_STARTED_AT=""
LOCK_SESSION_UUID=""
LOCK_STARTED_AT=""
LOCK_BACKEND_PORT=""
LOCK_FRONTEND_PORT=""

DRY_RUN=0
SENSOR_DISABLED=0
SHUTDOWN_DONE=0
INTERRUPTED=0
SKIP_BACKEND_HEALTHCHECK="${ZEINAGUARD_SKIP_BACKEND_HEALTHCHECK:-0}"
SKIP_FRONTEND_HEALTHCHECK="${ZEINAGUARD_SKIP_FRONTEND_HEALTHCHECK:-0}"
SENSOR_MAX_RETRIES=1

declare -a PREFLIGHT_ERRORS=()
declare -a PREFLIGHT_NOTES=()
declare -a BACKEND_RETRY_DELAYS=(1 1 2 2 3 3 5 5 8 10)
declare -a STARTUP_ORDER=("backend" "frontend" "sensor")
declare -a SHUTDOWN_ORDER=("sensor" "frontend" "backend")

usage() {
  cat <<'EOF'
Usage: ./run.sh [--dry-run] [--help]

Options:
  --dry-run   Run reconciliation, preflight, and port allocation without
              starting services or modifying the active lock session.
  --help      Show this help message.
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        printf '[run.sh][error] Unknown argument: %s\n' "$1" >&2
        exit 1
        ;;
    esac
    shift
  done
}

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

is_dry_run() {
  [ "$DRY_RUN" -eq 1 ]
}

dry_run_log() {
  printf '[run.sh][dry-run] %s\n' "$*"
}

current_user() {
  id -un
}

generate_uuid() {
  if [ -r /proc/sys/kernel/random/uuid ]; then
    cat /proc/sys/kernel/random/uuid
    return
  fi

  python3 - <<'PY'
import uuid
print(uuid.uuid4())
PY
}

service_requested_port() {
  case "$1" in
    backend) printf '%s\n' "$BACKEND_REQUESTED_PORT" ;;
    frontend) printf '%s\n' "$FRONTEND_REQUESTED_PORT" ;;
    sensor) printf 'n/a\n' ;;
    *) return 1 ;;
  esac
}

service_port_attempts() {
  case "$1" in
    backend) printf '%s\n' "$BACKEND_PORT_MAX_ATTEMPTS" ;;
    frontend) printf '%s\n' "$FRONTEND_PORT_MAX_ATTEMPTS" ;;
    sensor) printf '0\n' ;;
    *) return 1 ;;
  esac
}

service_port_for_session() {
  local service_name="$1"
  local session_uuid="$2"

  case "$service_name" in
    sensor)
      printf 'n/a\n'
      ;;
    backend)
      if [ "$session_uuid" = "$SESSION_UUID" ]; then
        printf '%s\n' "$FINAL_BACKEND_PORT"
      else
        printf '%s\n' "$LOCK_BACKEND_PORT"
      fi
      ;;
    frontend)
      if [ "$session_uuid" = "$SESSION_UUID" ]; then
        printf '%s\n' "$FINAL_FRONTEND_PORT"
      else
        printf '%s\n' "$LOCK_FRONTEND_PORT"
      fi
      ;;
    *)
      return 1
      ;;
  esac
}

record_service_event() {
  local service_name="$1"
  local event_name="$2"
  local reason="${3:-}"
  local pid_override="${4:-none}"
  local port_override="${5:-${SERVICE_PORT[$service_name]:-n/a}}"
  local retry_override="${6:-${SERVICE_RETRY[$service_name]:-0}}"
  local log_file="${SERVICE_LOG[$service_name]}"
  local session_value="${SESSION_UUID:-${LOCK_SESSION_UUID:-unlocked}}"
  local message=""

  message="ts=\"$(timestamp)\" session_uuid=${session_value} service=${service_name} event=${event_name} pid=${pid_override:-none} port=${port_override:-n/a} retry=${retry_override}"
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
  printf '%s %s\n' "$(timestamp)" "----- ZeinaGuard session boundary -----" >>"$FRONTEND_LOG"
  printf '%s %s\n' "$(timestamp)" "----- ZeinaGuard session boundary -----" >>"$BACKEND_LOG"
  printf '%s %s\n' "$(timestamp)" "----- ZeinaGuard session boundary -----" >>"$SENSOR_LOG"
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$ENV_FILE"
    set +a
  fi

  SKIP_BACKEND_HEALTHCHECK="${ZEINAGUARD_SKIP_BACKEND_HEALTHCHECK:-0}"
  SKIP_FRONTEND_HEALTHCHECK="${ZEINAGUARD_SKIP_FRONTEND_HEALTHCHECK:-0}"

  export ZEINAGUARD_NONINTERACTIVE=1
  export PYTHONUNBUFFERED=1
}

clear_loaded_lock() {
  LOCK_SESSION_UUID=""
  LOCK_STARTED_AT=""
  LOCK_BACKEND_PORT=""
  LOCK_FRONTEND_PORT=""
}

load_lock_file() {
  local key=""
  local value=""

  clear_loaded_lock
  [ -f "$LOCK_FILE" ] || return 1

  while IFS='=' read -r key value; do
    case "$key" in
      session_uuid) LOCK_SESSION_UUID="$value" ;;
      start_timestamp) LOCK_STARTED_AT="$value" ;;
      backend_port) LOCK_BACKEND_PORT="$value" ;;
      frontend_port) LOCK_FRONTEND_PORT="$value" ;;
    esac
  done <"$LOCK_FILE"

  [ -n "$LOCK_SESSION_UUID" ]
}

write_lock_file() {
  cat >"$LOCK_FILE" <<EOF
session_uuid=${SESSION_UUID}
start_timestamp=${SESSION_STARTED_AT}
backend_port=${FINAL_BACKEND_PORT}
frontend_port=${FINAL_FRONTEND_PORT}
EOF
}

remove_lock_file_if_current_session() {
  if load_lock_file && [ "$LOCK_SESSION_UUID" = "$SESSION_UUID" ]; then
    rm -f "$LOCK_FILE"
  fi
  clear_loaded_lock
}

refresh_runtime_environment() {
  BACKEND_URL="http://127.0.0.1:${FINAL_BACKEND_PORT}"

  SERVICE_PORT[backend]="$FINAL_BACKEND_PORT"
  SERVICE_PORT[frontend]="$FINAL_FRONTEND_PORT"
  SERVICE_PORT[sensor]="n/a"

  export SESSION_UUID
  export SESSION_STARTED_AT
  export FINAL_FRONTEND_PORT
  export FINAL_BACKEND_PORT
  export FRONTEND_PORT="$FINAL_FRONTEND_PORT"
  export BACKEND_PORT="$FINAL_BACKEND_PORT"
  export FLASK_PORT="$FINAL_BACKEND_PORT"
  export PORT="$FINAL_FRONTEND_PORT"
  export BACKEND_URL
  export NEXT_PUBLIC_API_URL="$BACKEND_URL"
  export NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL"
  export ZEINAGUARD_LOCK_FILE="$LOCK_FILE"
  export ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR"
  export ZEINAGUARD_SUPERVISOR_PID="$$"
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

pid_cwd() {
  local pid="$1"
  [ -L "/proc/$pid/cwd" ] || return 1
  readlink -f "/proc/$pid/cwd" 2>/dev/null || true
}

pid_ppid() {
  local pid="$1"
  [ -r "/proc/$pid/status" ] || return 1
  awk '/^PPid:/ {print $2; exit}' "/proc/$pid/status"
}

pid_group() {
  local pid="$1"
  ps -o pgid= -p "$pid" 2>/dev/null | awk 'NR==1 {gsub(/[[:space:]]/, "", $1); print $1}'
}

pid_environ_contains() {
  local pid="$1"
  local expected="$2"
  [ -r "/proc/$pid/environ" ] || return 1
  tr '\0' '\n' <"/proc/$pid/environ" | grep -Fxq "$expected"
}

cmdline_matches_service_signature() {
  local service_name="$1"
  local cmdline="$2"

  case "$service_name" in
    backend)
      [[ "$cmdline" == *"$BACKEND_DIR/app.py"* ]] || [[ "$cmdline" == *"backend/app.py"* ]]
      ;;
    frontend)
      [[ "$cmdline" == *"next dev"* ]] || [[ "$cmdline" == *"$FRONTEND_NEXT_BIN"* ]]
      ;;
    sensor)
      [[ "$cmdline" == *"$SENSOR_MAIN"* ]] || [[ "$cmdline" == *"sensor/main.py"* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

ancestor_chain_has_session() {
  local pid="$1"
  local session_uuid="$2"
  local ancestor=""
  local safety=0

  ancestor="$(pid_ppid "$pid" || true)"
  while [ -n "$ancestor" ] && [ "$ancestor" -gt 1 ] 2>/dev/null; do
    if pid_environ_contains "$ancestor" "ZEINAGUARD_SESSION_UUID=$session_uuid" \
      && pid_environ_contains "$ancestor" "ZEINAGUARD_LOCK_FILE=$LOCK_FILE"; then
      return 0
    fi
    ancestor="$(pid_ppid "$ancestor" || true)"
    safety=$((safety + 1))
    [ "$safety" -lt 64 ] || break
  done

  return 1
}

fingerprint_process() {
  local service_name="$1"
  local pid="$2"
  local session_uuid="$3"
  local cmdline=""
  local cwd=""

  pid_is_alive "$pid" || return 1

  cmdline="$(pid_cmdline "$pid" || true)"
  [ -n "$cmdline" ] || return 1
  [[ "$cmdline" == *"$ROOT_DIR"* ]] || return 1
  cmdline_matches_service_signature "$service_name" "$cmdline" || return 1

  cwd="$(pid_cwd "$pid" || true)"
  [ -n "$cwd" ] || return 1
  [[ "$cwd" == "$ROOT_DIR"* ]] || return 1

  pid_environ_contains "$pid" "ZEINAGUARD_SESSION_UUID=$session_uuid" || return 1
  pid_environ_contains "$pid" "ZEINAGUARD_LOCK_FILE=$LOCK_FILE" || return 1
  pid_environ_contains "$pid" "ZEINAGUARD_PROJECT_ROOT=$ROOT_DIR" || return 1
  ancestor_chain_has_session "$pid" "$session_uuid" || return 1
}

port_has_listener() {
  local port="$1"
  ss -ltnH "( sport = :$port )" 2>/dev/null | grep -q .
}

listener_pids_for_port() {
  local port="$1"
  ss -ltnpH "( sport = :$port )" 2>/dev/null | grep -o 'pid=[0-9]\+' | cut -d= -f2 | sort -u || true
}

warn_external_process() {
  local service_name="$1"
  local pid="$2"
  local reason="$3"
  warn "Skipping external process for $service_name (pid $pid): $reason"
  record_service_event "$service_name" "external-process-skipped" "$reason" "$pid" "${SERVICE_PORT[$service_name]:-n/a}"
}

ps_candidates_for_service() {
  local service_name="$1"
  local line=""
  local pid=""
  local args=""

  while IFS= read -r line; do
    [ -n "$line" ] || continue
    line="${line#"${line%%[![:space:]]*}"}"
    pid="${line%% *}"
    args="${line#* }"
    [ -n "$pid" ] || continue
    [ -n "$args" ] || continue
    [[ "$args" == *"$ROOT_DIR"* ]] || continue
    if cmdline_matches_service_signature "$service_name" "$args"; then
      printf '%s\n' "$pid"
    fi
  done < <(ps -eo pid=,args= 2>/dev/null)
}

find_service_candidates() {
  local service_name="$1"
  local hinted_port="$2"

  if [ -n "$hinted_port" ] && [ "$hinted_port" != "n/a" ]; then
    listener_pids_for_port "$hinted_port"
  fi

  ps_candidates_for_service "$service_name"
}

find_verified_service_pids() {
  local service_name="$1"
  local session_uuid="$2"
  local hinted_port="$3"
  local pid=""
  declare -A seen=()

  while read -r pid; do
    [ -n "$pid" ] || continue
    if [ -n "${seen[$pid]:-}" ]; then
      continue
    fi
    seen["$pid"]=1

    if fingerprint_process "$service_name" "$pid" "$session_uuid"; then
      printf '%s\n' "$pid"
    else
      if pid_is_alive "$pid"; then
        warn_external_process "$service_name" "$pid" "fingerprint validation failed"
      fi
    fi
  done < <(find_service_candidates "$service_name" "$hinted_port")
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

terminate_verified_service_pid() {
  local service_name="$1"
  local pid="$2"
  local reason="$3"
  local port_value="$4"
  local retry_value="${SERVICE_RETRY[$service_name]:-0}"
  local pgid=""

  pgid="$(pid_group "$pid" || true)"
  record_service_event "$service_name" "stop-requested" "$reason" "$pid" "$port_value" "$retry_value"

  if is_dry_run; then
    dry_run_log "Would stop $service_name pid=$pid pgid=${pgid:-unknown} port=${port_value:-n/a} reason=$reason"
    return 0
  fi

  if [ -n "$pgid" ]; then
    kill -TERM -- "-$pgid" >/dev/null 2>&1 || true
  fi
  kill -TERM "$pid" >/dev/null 2>&1 || true

  if ! wait_for_pid_exit "$pid" 10; then
    record_service_event "$service_name" "stop-escalated" "TERM timeout, sending KILL" "$pid" "$port_value" "$retry_value"
    if [ -n "$pgid" ]; then
      kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
    fi
    kill -KILL "$pid" >/dev/null 2>&1 || true
    wait_for_pid_exit "$pid" 5 || true
  fi

  record_service_event "$service_name" "stopped" "$reason" "$pid" "$port_value" "$retry_value"
}

stop_service_for_session() {
  local service_name="$1"
  local session_uuid="$2"
  local reason="$3"
  local hinted_port="${4:-}"
  local pid=""
  local found=0

  while read -r pid; do
    [ -n "$pid" ] || continue
    found=1
    terminate_verified_service_pid "$service_name" "$pid" "$reason" "${hinted_port:-${SERVICE_PORT[$service_name]:-n/a}}"
  done < <(find_verified_service_pids "$service_name" "$session_uuid" "$hinted_port")

  [ "$found" -eq 1 ] || return 0
}

session_has_live_service() {
  local service_name="$1"
  local session_uuid="$2"
  local hinted_port="${3:-}"
  local pid=""

  while read -r pid; do
    [ -n "$pid" ] || continue
    return 0
  done < <(find_verified_service_pids "$service_name" "$session_uuid" "$hinted_port")

  return 1
}

session_has_live_processes() {
  local session_uuid="$1"
  local service_name=""

  for service_name in "${STARTUP_ORDER[@]}"; do
    if session_has_live_service "$service_name" "$session_uuid" "$(service_port_for_session "$service_name" "$session_uuid")"; then
      return 0
    fi
  done

  return 1
}

reconcile_existing_session() {
  if ! load_lock_file; then
    return 0
  fi

  log "Reconciling existing lock session $LOCK_SESSION_UUID"

  stop_service_for_session "sensor" "$LOCK_SESSION_UUID" "startup reconciliation" "n/a"
  stop_service_for_session "frontend" "$LOCK_SESSION_UUID" "startup reconciliation" "$LOCK_FRONTEND_PORT"
  stop_service_for_session "backend" "$LOCK_SESSION_UUID" "startup reconciliation" "$LOCK_BACKEND_PORT"

  if is_dry_run; then
    if session_has_live_processes "$LOCK_SESSION_UUID"; then
      dry_run_log "Would replace active lock session $LOCK_SESSION_UUID after stopping its verified processes"
    else
      dry_run_log "Would replace stale lock session $LOCK_SESSION_UUID"
    fi
    clear_loaded_lock
    return 0
  fi

  if session_has_live_processes "$LOCK_SESSION_UUID"; then
    fail "Existing ZeinaGuard lock session could not be reconciled safely"
  fi

  rm -f "$LOCK_FILE"

  clear_loaded_lock
}

resolve_service_port() {
  local service_name="$1"
  local requested_port="$2"
  local max_attempts="$3"
  local target_var="$4"
  local offset=0
  local candidate=""
  local pids=""
  local pid=""

  while [ "$offset" -lt "$max_attempts" ]; do
    candidate=$((requested_port + offset))

    if ! port_has_listener "$candidate"; then
      printf -v "$target_var" '%s' "$candidate"
      PREFLIGHT_NOTES+=("${service_name} port selected: $candidate")
      return 0
    fi

    pids="$(listener_pids_for_port "$candidate")"
    if [ -z "$pids" ]; then
      warn "${service_name} port $candidate is in use and listener details are unavailable; trying next port"
    else
      while read -r pid; do
        [ -n "$pid" ] || continue
        warn_external_process "$service_name" "$pid" "port $candidate is busy and not owned by the active lock session"
      done <<<"$pids"
    fi

    offset=$((offset + 1))
  done

  PREFLIGHT_ERRORS+=("No free ${service_name} port was found in the fallback range starting at ${requested_port}")
  return 1
}

resolve_runtime_ports() {
  resolve_service_port "backend" "$BACKEND_REQUESTED_PORT" "$BACKEND_PORT_MAX_ATTEMPTS" FINAL_BACKEND_PORT || return 1
  resolve_service_port "frontend" "$FRONTEND_REQUESTED_PORT" "$FRONTEND_PORT_MAX_ATTEMPTS" FINAL_FRONTEND_PORT || return 1
  refresh_runtime_environment
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
  local deadline=$((SECONDS + ${1:-10}))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if python3 - "$BACKEND_URL" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
url = f"{base}/socket.io/?transport=polling&EIO=4&t=supervisor"

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

  if [ "$SKIP_BACKEND_HEALTHCHECK" = "1" ]; then
    record_service_event "backend" "health-skipped" "backend health checks skipped by configuration" "${SERVICE_RUNTIME_PID[backend]:-none}" "$FINAL_BACKEND_PORT"
    log "Backend health gate skipped by configuration"
    return 0
  fi

  while [ "$attempt" -lt "$max_attempts" ]; do
    if ! session_has_live_service "backend" "$SESSION_UUID" "$FINAL_BACKEND_PORT"; then
      return 1
    fi

    if wait_for_http "$BACKEND_URL/health" 2 status healthy \
      && wait_for_http "$BACKEND_URL/ready" 2 ready True \
      && wait_for_backend_socketio 2; then
      record_service_event "backend" "health-passed" "backend passed health gates" "${SERVICE_RUNTIME_PID[backend]:-none}" "$FINAL_BACKEND_PORT"
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

sensor_command_overridden() {
  [ -n "${ZEINAGUARD_SENSOR_CMD_OVERRIDE:-}" ]
}

backend_command_overridden() {
  [ -n "${ZEINAGUARD_BACKEND_CMD_OVERRIDE:-}" ]
}

frontend_command_overridden() {
  [ -n "${ZEINAGUARD_FRONTEND_CMD_OVERRIDE:-}" ]
}

run_sensor_command() {
  if sensor_command_overridden; then
    env ZEINAGUARD_SESSION_UUID="${SESSION_UUID:-${LOCK_SESSION_UUID:-preflight}}" \
      ZEINAGUARD_LOCK_FILE="$LOCK_FILE" \
      ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
      ZEINAGUARD_SERVICE="sensor" \
      BACKEND_URL="$BACKEND_URL" \
      SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
      SENSOR_LOG_FILE="$SENSOR_LOG" \
      sudo -n -E bash -lc "$ZEINAGUARD_SENSOR_CMD_OVERRIDE" -- "$@"
    return
  fi

  env ZEINAGUARD_SESSION_UUID="${SESSION_UUID:-${LOCK_SESSION_UUID:-preflight}}" \
    ZEINAGUARD_LOCK_FILE="$LOCK_FILE" \
    ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
    ZEINAGUARD_SERVICE="sensor" \
    BACKEND_URL="$BACKEND_URL" \
    SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" \
    SENSOR_LOG_FILE="$SENSOR_LOG" \
    sudo -n -E "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN" "$@"
}

validate_sensor_sudo() {
  local output=""
  local compact_output=""

  sudo -k >/dev/null 2>&1 || true
  if ! sudo -n true >/dev/null 2>&1; then
    PREFLIGHT_ERRORS+=("Sensor requires passwordless sudo (NOPASSWD)")
    return 1
  fi

  if output="$(run_sensor_command --test 2>&1)"; then
    [ -n "$output" ] && printf '%s\n' "$output" | awk -v prefix="[sensor] " '{ print prefix $0; fflush() }' >>"$SENSOR_LOG"
    PREFLIGHT_NOTES+=("Privileged sensor self-test passed")
    return 0
  fi

  [ -n "$output" ] && printf '%s\n' "$output" | awk -v prefix="[sensor] " '{ print prefix $0; fflush() }' >>"$SENSOR_LOG"
  compact_output="$(compact_text "$output")"

  if printf '%s' "$output" | grep -qi 'password .*required'; then
    PREFLIGHT_ERRORS+=("Sensor requires passwordless sudo (NOPASSWD)")
  else
    PREFLIGHT_ERRORS+=("Sensor privileged self-test failed. See $SENSOR_LOG")
  fi
  [ -n "$compact_output" ] && PREFLIGHT_ERRORS+=("Sensor validation output: $compact_output")
  return 1
}

require_directory() {
  local path="$1"
  local description="$2"
  [ -d "$path" ] || PREFLIGHT_ERRORS+=("$description is missing: $path")
}

require_file() {
  local path="$1"
  local description="$2"
  [ -f "$path" ] || PREFLIGHT_ERRORS+=("$description is missing: $path")
}

validate_command() {
  local command_name="$1"
  local hint="${2:-}"

  if command_exists "$command_name"; then
    return 0
  fi

  if [ -n "$hint" ]; then
    PREFLIGHT_ERRORS+=("Required command is not installed: $command_name. $hint")
  else
    PREFLIGHT_ERRORS+=("Required command is not installed: $command_name")
  fi
}

ensure_pnpm() {
  if command_exists pnpm; then
    return 0
  fi

  if ! command_exists npm; then
    PREFLIGHT_ERRORS+=("pnpm is missing and npm is unavailable. Install Node.js and pnpm before running ZeinaGuard.")
    return 1
  fi

  PREFLIGHT_ERRORS+=("pnpm is missing. Install it before running ZeinaGuard.")
  return 1
}

validate_python_runtime() {
  python3 -m pip --version >/dev/null 2>&1 || PREFLIGHT_ERRORS+=("python3 pip is unavailable. Install python3-pip.")
  python3 -m venv --help >/dev/null 2>&1 || PREFLIGHT_ERRORS+=("python3 venv support is unavailable. Install python3-venv.")
}

validate_venv_python() {
  local service_name="$1"
  local python_bin="$2"

  if [ ! -x "$python_bin" ]; then
    PREFLIGHT_ERRORS+=("${service_name} virtual environment Python is missing: $python_bin")
    return
  fi

  "$python_bin" -m pip --version >/dev/null 2>&1 || PREFLIGHT_ERRORS+=("${service_name} virtual environment pip is unavailable")
}

validate_python_file() {
  local python_bin="$1"
  local path="$2"
  local description="$3"

  "$python_bin" -m py_compile "$path" >/dev/null 2>&1 || PREFLIGHT_ERRORS+=("$description failed Python compilation: $path")
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
    PREFLIGHT_ERRORS+=("Do not run run.sh as root. Backend and frontend must remain unprivileged.")
  fi

  require_directory "$BACKEND_DIR" "Backend directory"
  require_directory "$SENSOR_DIR" "Sensor directory"
  require_file "$FRONTEND_DIR/package.json" "Frontend package manifest"
  require_file "$BACKEND_DIR/app.py" "Backend entrypoint"
  require_file "$SENSOR_MAIN" "Sensor entrypoint"

  if ! frontend_command_overridden; then
    validate_command node "Install Node.js first."
  fi
  validate_command python3 "Install Python 3 first."
  validate_command sudo "Install sudo and configure NOPASSWD for the sensor."
  validate_command setsid "Install util-linux so services can run in isolated process groups."
  validate_command ss "Install iproute2 so ports can be inspected safely."
  validate_command ps "Install procps so process ancestry can be verified."
  validate_command readlink "Install coreutils so process cwd validation works."

  if frontend_command_overridden; then
    PREFLIGHT_NOTES+=("Using frontend override command; skipping pnpm checks")
  else
    ensure_pnpm || true
  fi

  validate_python_runtime

  if ! command_exists ip && ! command_exists iwconfig; then
    PREFLIGHT_ERRORS+=("Wireless interface discovery requires iproute2 or wireless-tools")
  fi

  if backend_command_overridden; then
    PREFLIGHT_NOTES+=("Using backend override command; skipping backend virtualenv validation")
  elif [ -d "$BACKEND_DIR/.venv" ]; then
    validate_venv_python "backend" "$BACKEND_VENV_PYTHON"
    validate_python_file "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py" "Backend entrypoint"
  else
    PREFLIGHT_ERRORS+=("Backend virtual environment is missing: $BACKEND_DIR/.venv")
  fi

  if sensor_command_overridden; then
    PREFLIGHT_NOTES+=("Using sensor override command; skipping sensor virtualenv validation")
  elif [ -d "$SENSOR_DIR/.venv" ]; then
    validate_venv_python "sensor" "$SENSOR_VENV_PYTHON"
    validate_python_file "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN" "Sensor entrypoint"
  else
    PREFLIGHT_ERRORS+=("Sensor virtual environment is missing: $SENSOR_DIR/.venv")
  fi

  if ! frontend_command_overridden && [ -d "$FRONTEND_DIR/node_modules" ]; then
    PREFLIGHT_NOTES+=("Frontend dependencies already cached in node_modules")
  elif ! frontend_command_overridden; then
    PREFLIGHT_NOTES+=("node_modules is missing; pnpm install will run before startup")
  fi

  if [ "${#PREFLIGHT_ERRORS[@]}" -eq 0 ]; then
    if ! select_sensor_interface; then
      PREFLIGHT_ERRORS+=("No usable wireless interface found. Set SENSOR_INTERFACE or attach a wireless adapter.")
    else
      PREFLIGHT_NOTES+=("Using sensor interface: $SELECTED_SENSOR_INTERFACE")
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
  if frontend_command_overridden; then
    log "Frontend override command configured; skipping dependency install"
    return
  fi

  if [ -d "$FRONTEND_DIR/node_modules" ]; then
    log "Reusing cached frontend dependencies"
    [ -x "$FRONTEND_NEXT_BIN" ] || fail "Next.js binary is missing: $FRONTEND_NEXT_BIN"
    return
  fi

  log "Installing frontend dependencies with pnpm"
  (
    cd "$FRONTEND_DIR"
    pnpm install
  )

  [ -x "$FRONTEND_NEXT_BIN" ] || fail "Next.js binary is missing after pnpm install: $FRONTEND_NEXT_BIN"
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

  local wrapper_pid=""
  local failure_reason=""

  SERVICE_PORT["$service_name"]="$service_port"
  record_service_event "$service_name" "start-requested" "launching service" "pending" "$service_port"

  (
    cd "$workdir"
    exec env ZEINAGUARD_SESSION_UUID="$SESSION_UUID" \
      ZEINAGUARD_LOCK_FILE="$LOCK_FILE" \
      ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
      ZEINAGUARD_SUPERVISOR_PID="$$" \
      ZEINAGUARD_SERVICE="$service_name" \
      setsid bash -lc '
        set -o pipefail
        service_name="$1"
        shift
        "$@" 2>&1 | awk -v prefix="[""$service_name""] " '"'"'{ print prefix $0; fflush() }'"'"'
      ' _ "$service_name" "$@"
  ) >>"$log_file" 2>&1 &

  wrapper_pid="$!"
  SERVICE_RUNTIME_PID["$service_name"]="$wrapper_pid"
  record_service_event "$service_name" "started" "service wrapper launched" "$wrapper_pid" "$service_port"
  log "Started $service_name (wrapper pid $wrapper_pid, port $service_port)"

  sleep 2
  if session_has_live_service "$service_name" "$SESSION_UUID" "$service_port"; then
    return 0
  fi

  failure_reason="$(recent_log_excerpt "$log_file" 40)"
  record_service_event "$service_name" "startup-failed" "${failure_reason:-failed to stay running}" "$wrapper_pid" "$service_port"
  return 1
}

launch_backend() {
  if backend_command_overridden; then
    start_service "backend" "$BACKEND_DIR" "$BACKEND_LOG" "$FINAL_BACKEND_PORT" \
      bash -lc "$ZEINAGUARD_BACKEND_CMD_OVERRIDE"
    return
  fi

  start_service "backend" "$BACKEND_DIR" "$BACKEND_LOG" "$FINAL_BACKEND_PORT" \
    "$BACKEND_VENV_PYTHON" "$BACKEND_DIR/app.py"
}

launch_frontend() {
  if frontend_command_overridden; then
    start_service "frontend" "$FRONTEND_DIR" "$FRONTEND_LOG" "$FINAL_FRONTEND_PORT" \
      bash -lc "$ZEINAGUARD_FRONTEND_CMD_OVERRIDE"
    return
  fi

  start_service "frontend" "$FRONTEND_DIR" "$FRONTEND_LOG" "$FINAL_FRONTEND_PORT" \
    "$FRONTEND_NEXT_BIN" dev --port "$FINAL_FRONTEND_PORT" --hostname 0.0.0.0
}

launch_sensor_once() {
  if sensor_command_overridden; then
    start_service "sensor" "$SENSOR_DIR" "$SENSOR_LOG" "n/a" \
      sudo -n -E bash -lc "$ZEINAGUARD_SENSOR_CMD_OVERRIDE"
    return
  fi

  start_service "sensor" "$SENSOR_DIR" "$SENSOR_LOG" "n/a" \
    sudo -n -E "$SENSOR_VENV_PYTHON" "$SENSOR_MAIN"
}

disable_sensor() {
  local reason="$1"
  SENSOR_DISABLED=1
  record_service_event "sensor" "disabled" "$reason" "${SERVICE_RUNTIME_PID[sensor]:-none}" "n/a" "${SERVICE_RETRY[sensor]}"
  warn "Sensor disabled: $reason"
  stop_service_for_session "sensor" "$SESSION_UUID" "$reason" "n/a"
}

start_sensor_service() {
  local startup_reason=""

  if launch_sensor_once; then
    return 0
  fi

  startup_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
  record_service_event "sensor" "startup-failed" "${startup_reason:-unknown}" "${SERVICE_RUNTIME_PID[sensor]:-none}" "n/a" "${SERVICE_RETRY[sensor]}"

  if [ "${SERVICE_RETRY[sensor]}" -lt "$SENSOR_MAX_RETRIES" ]; then
    SERVICE_RETRY[sensor]=$((SERVICE_RETRY[sensor] + 1))
    warn "Sensor exited during startup. Restarting once (${SERVICE_RETRY[sensor]}/${SENSOR_MAX_RETRIES}). Reason: ${startup_reason:-unknown}"
    sleep 2
    if launch_sensor_once; then
      return 0
    fi
    startup_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
    record_service_event "sensor" "startup-retry-failed" "${startup_reason:-unknown}" "${SERVICE_RUNTIME_PID[sensor]:-none}" "n/a" "${SERVICE_RETRY[sensor]}"
  fi

  disable_sensor "sensor failed to stay running after $((SERVICE_RETRY[sensor] + 1)) attempts: ${startup_reason:-unknown}"
  return 0
}

print_summary() {
  local sensor_state="active"

  if [ "$SENSOR_DISABLED" -eq 1 ]; then
    sensor_state="disabled"
  fi

  cat <<EOF
ZeinaGuard is running
Session UUID : ${SESSION_UUID}
Frontend URL : http://127.0.0.1:${FINAL_FRONTEND_PORT}
Backend URL  : ${BACKEND_URL}
Sensor       : ${sensor_state}
Logs         : ${LOG_DIR}
Lock file    : ${LOCK_FILE}
EOF
}

print_dry_run_summary() {
  cat <<EOF
ZeinaGuard dry-run completed
Session UUID : ${SESSION_UUID}
Frontend URL : http://127.0.0.1:${FINAL_FRONTEND_PORT}
Backend URL  : ${BACKEND_URL}
Lock file    : ${LOCK_FILE}
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
    stop_service_for_session "$service_name" "$SESSION_UUID" "supervisor shutdown" "$(service_port_for_session "$service_name" "$SESSION_UUID")"
  done

  if ! session_has_live_processes "$SESSION_UUID"; then
    remove_lock_file_if_current_session
  fi

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
    if ! session_has_live_service "backend" "$SESSION_UUID" "$FINAL_BACKEND_PORT"; then
      failure_reason="$(recent_log_excerpt "$BACKEND_LOG" 40)"
      record_service_event "backend" "unexpected-exit" "${failure_reason:-unknown}" "${SERVICE_RUNTIME_PID[backend]:-none}" "$FINAL_BACKEND_PORT"
      fail "Backend exited unexpectedly. Reason: ${failure_reason:-unknown}. See $BACKEND_LOG"
    fi

    if ! session_has_live_service "frontend" "$SESSION_UUID" "$FINAL_FRONTEND_PORT"; then
      failure_reason="$(recent_log_excerpt "$FRONTEND_LOG" 40)"
      record_service_event "frontend" "unexpected-exit" "${failure_reason:-unknown}" "${SERVICE_RUNTIME_PID[frontend]:-none}" "$FINAL_FRONTEND_PORT"
      fail "Frontend exited unexpectedly. Reason: ${failure_reason:-unknown}. See $FRONTEND_LOG"
    fi

    if [ "$SENSOR_DISABLED" -eq 0 ] && ! session_has_live_service "sensor" "$SESSION_UUID" "n/a"; then
      failure_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
      record_service_event "sensor" "unexpected-exit" "${failure_reason:-unknown}" "${SERVICE_RUNTIME_PID[sensor]:-none}" "n/a" "${SERVICE_RETRY[sensor]}"

      if [ "${SERVICE_RETRY[sensor]}" -lt "$SENSOR_MAX_RETRIES" ]; then
        SERVICE_RETRY[sensor]=$((SERVICE_RETRY[sensor] + 1))
        warn "Sensor exited unexpectedly. Restarting once (${SERVICE_RETRY[sensor]}/${SENSOR_MAX_RETRIES}). Reason: ${failure_reason:-unknown}"
        stop_service_for_session "sensor" "$SESSION_UUID" "sensor restart requested" "n/a"
        sleep 2
        if launch_sensor_once; then
          continue
        fi
        failure_reason="$(recent_log_excerpt "$SENSOR_LOG" 40)"
        record_service_event "sensor" "restart-failed" "${failure_reason:-unknown}" "${SERVICE_RUNTIME_PID[sensor]:-none}" "n/a" "${SERVICE_RETRY[sensor]}"
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
  reconcile_existing_session

  SESSION_UUID="$(generate_uuid)"
  SESSION_STARTED_AT="$(timestamp)"
  resolve_runtime_ports || exit 1

  if is_dry_run; then
    dry_run_log "Backend would start on port $FINAL_BACKEND_PORT"
    dry_run_log "Frontend would start on port $FINAL_FRONTEND_PORT"
    dry_run_log "Sensor would start only after backend and frontend are healthy"
    print_dry_run_summary
    return 0
  fi

  refresh_runtime_environment
  write_lock_file
  ensure_frontend_dependencies

  log "Starting backend on port $FINAL_BACKEND_PORT"
  launch_backend || fail "backend failed to stay running. See $BACKEND_LOG"
  wait_for_backend_health || fail "Backend failed health gating. See $BACKEND_LOG"

  log "Starting frontend on port $FINAL_FRONTEND_PORT"
  launch_frontend || fail "frontend failed to stay running. See $FRONTEND_LOG"

  if [ "$SKIP_FRONTEND_HEALTHCHECK" = "1" ]; then
    record_service_event "frontend" "health-skipped" "frontend health checks skipped by configuration" "${SERVICE_RUNTIME_PID[frontend]:-none}" "$FINAL_FRONTEND_PORT"
    log "Frontend health gate skipped by configuration"
  else
    wait_for_http "http://127.0.0.1:${FINAL_FRONTEND_PORT}" 20 || fail "Frontend failed health check. See $FRONTEND_LOG"
    record_service_event "frontend" "health-passed" "frontend HTTP gate passed" "${SERVICE_RUNTIME_PID[frontend]:-none}" "$FINAL_FRONTEND_PORT"
  fi

  log "Starting sensor"
  start_sensor_service

  print_summary
  monitor_services
}

parse_args "$@"
main
