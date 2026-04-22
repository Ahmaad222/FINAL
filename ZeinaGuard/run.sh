#!/usr/bin/env bash
set -uo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
SENSOR_DIR="$ROOT_DIR/sensor"
ENV_FILE="$ROOT_DIR/.env"

RUNTIME_DIR="${ZEINAGUARD_RUNTIME_DIR:-$ROOT_DIR/.runtime}"
LOG_DIR="${ZEINAGUARD_LOG_DIR:-$ROOT_DIR/logs}"
PID_DIR="$RUNTIME_DIR/pids"
LOCK_FILE="${ZEINAGUARD_LOCK_FILE:-/tmp/zeinaguard.lock}"

SUPERVISOR_LOG="$LOG_DIR/supervisor.log"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"
SENSOR_LOG="$LOG_DIR/sensor.log"

CURRENT_USER_NAME="$(id -un 2>/dev/null || printf 'unknown')"

REQUESTED_FRONTEND_PORT=""
REQUESTED_BACKEND_PORT=""
FINAL_FRONTEND_PORT=""
FINAL_BACKEND_PORT=""
BACKEND_URL=""
FRONTEND_URL=""
SESSION_UUID=""
SESSION_STARTED_AT=""
SELECTED_SENSOR_INTERFACE=""
BACKEND_PYTHON=""
SENSOR_PYTHON=""
FRONTEND_NEXT_BIN="$ROOT_DIR/node_modules/.bin/next"

DRY_RUN=0
RUN_TESTS=0
SHUTDOWN_REQUESTED=0
SHUTDOWN_DONE=0
INTERRUPTED=0
SENSOR_DISABLED=0
SENSOR_DISABLE_REASON=""
SENSOR_RETRY_COUNT=0
SENSOR_MAX_RETRIES=1
USE_SETSID=0
PORT_FALLBACK_COUNT=5
MONITOR_INTERVAL="${ZEINAGUARD_MONITOR_INTERVAL:-2}"
BACKEND_HEALTH_TIMEOUT="${ZEINAGUARD_BACKEND_HEALTH_TIMEOUT:-45}"
FRONTEND_HEALTH_TIMEOUT="${ZEINAGUARD_FRONTEND_HEALTH_TIMEOUT:-60}"

declare -A SERVICE_PID=([backend]="" [frontend]="" [sensor]="")
declare -A SERVICE_PGID=([backend]="" [frontend]="" [sensor]="")
declare -A SERVICE_PORT=([backend]="" [frontend]="" [sensor]="n/a")
declare -A SERVICE_STARTED_AT=([backend]="" [frontend]="" [sensor]="")
declare -A SERVICE_LOG=(
  [backend]="$BACKEND_LOG"
  [frontend]="$FRONTEND_LOG"
  [sensor]="$SENSOR_LOG"
)
declare -A SERVICE_MATCH_TOKEN=([backend]="" [frontend]="" [sensor]="")

declare -A THROTTLE_WINDOW_START=()
declare -A THROTTLE_COUNT=()
declare -A THROTTLE_SUPPRESSED=()
declare -A THROTTLE_MESSAGE=()

usage() {
  cat <<'EOF'
Usage: ./run.sh [--dry-run] [--test] [--help]

Options:
  --dry-run   Validate, reconcile, and allocate ports without starting services.
  --test      Run the built-in stability simulations and print PASS/FAIL.
  --help      Show this help text.
EOF
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      --test)
        RUN_TESTS=1
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

compact_text() {
  printf '%s' "$*" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

is_numeric() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

ensure_runtime_dirs() {
  mkdir -p "$LOG_DIR" "$PID_DIR"
}

prepare_log_files() {
  touch "$SUPERVISOR_LOG" "$BACKEND_LOG" "$FRONTEND_LOG" "$SENSOR_LOG"
}

log() {
  local message
  message="$(compact_text "$*")"
  printf '%s [run.sh] %s\n' "$(timestamp)" "$message" | tee -a "$SUPERVISOR_LOG"
}

warn() {
  local message
  message="$(compact_text "$*")"
  printf '%s [run.sh][warn] %s\n' "$(timestamp)" "$message" | tee -a "$SUPERVISOR_LOG" >&2
}

error_log() {
  local message
  message="$(compact_text "$*")"
  printf '%s [run.sh][error] %s\n' "$(timestamp)" "$message" | tee -a "$SUPERVISOR_LOG" >&2
}

warn_throttled() {
  local key="$1"
  local message="$2"
  local now="${SECONDS:-0}"
  local start="${THROTTLE_WINDOW_START[$key]:-0}"
  local count="${THROTTLE_COUNT[$key]:-0}"
  local suppressed="${THROTTLE_SUPPRESSED[$key]:-0}"
  local window=10
  local limit=3

  if [ "$start" -eq 0 ] || [ $((now - start)) -ge "$window" ]; then
    if [ "$suppressed" -gt 0 ]; then
      warn "Suppressed ${suppressed} repeated warnings in the last ${window}s: ${THROTTLE_MESSAGE[$key]}"
    fi
    THROTTLE_WINDOW_START["$key"]="$now"
    THROTTLE_COUNT["$key"]=0
    THROTTLE_SUPPRESSED["$key"]=0
    THROTTLE_MESSAGE["$key"]="$message"
    count=0
  fi

  count=$((count + 1))
  THROTTLE_COUNT["$key"]="$count"
  THROTTLE_MESSAGE["$key"]="$message"

  if [ "$count" -le "$limit" ]; then
    warn "$message"
    return
  fi

  suppressed=$((suppressed + 1))
  THROTTLE_SUPPRESSED["$key"]="$suppressed"
  if [ "$suppressed" -eq 1 ]; then
    warn "Suppressing repeated warnings for 10s: $message"
  fi
}

flush_throttled_warnings() {
  local key=""
  for key in "${!THROTTLE_SUPPRESSED[@]}"; do
    if [ "${THROTTLE_SUPPRESSED[$key]:-0}" -gt 0 ]; then
      warn "Suppressed ${THROTTLE_SUPPRESSED[$key]} repeated warnings: ${THROTTLE_MESSAGE[$key]}"
      THROTTLE_SUPPRESSED["$key"]=0
    fi
  done
}

service_log_event() {
  local service="$1"
  local event="$2"
  local reason="${3:-}"
  local pid="${SERVICE_PID[$service]:-none}"
  local port="${SERVICE_PORT[$service]:-n/a}"
  local started="${SERVICE_STARTED_AT[$service]:-n/a}"
  printf '%s [supervisor] service=%s event=%s pid=%s port=%s start_time="%s" reason="%s"\n' \
    "$(timestamp)" \
    "$service" \
    "$event" \
    "${pid:-none}" \
    "${port:-n/a}" \
    "${started:-n/a}" \
    "$(compact_text "$reason")" >>"${SERVICE_LOG[$service]}"
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

load_env_file() {
  if [ "${ZEINAGUARD_IGNORE_ENV_FILE:-0}" = "1" ]; then
    return
  fi

  if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$ENV_FILE"
    set +a
  fi
}

refresh_config() {
  REQUESTED_FRONTEND_PORT="${ZEINAGUARD_FRONTEND_PORT:-${FRONTEND_PORT:-3000}}"
  REQUESTED_BACKEND_PORT="${ZEINAGUARD_BACKEND_PORT:-${BACKEND_PORT:-5000}}"
  PORT_FALLBACK_COUNT="${ZEINAGUARD_PORT_FALLBACK_COUNT:-5}"

  BACKEND_PYTHON="${ZEINAGUARD_BACKEND_PYTHON:-$BACKEND_DIR/.venv/bin/python}"
  SENSOR_PYTHON="${ZEINAGUARD_SENSOR_PYTHON:-$SENSOR_DIR/.venv/bin/python}"

  if [ ! -x "$BACKEND_PYTHON" ]; then
    BACKEND_PYTHON="${ZEINAGUARD_BACKEND_PYTHON_FALLBACK:-python3}"
  fi

  if [ ! -x "$SENSOR_PYTHON" ]; then
    SENSOR_PYTHON="${ZEINAGUARD_SENSOR_PYTHON_FALLBACK:-python3}"
  fi

  SERVICE_MATCH_TOKEN[backend]="$BACKEND_DIR/app.py"
  SERVICE_MATCH_TOKEN[frontend]="$FRONTEND_NEXT_BIN"
  SERVICE_MATCH_TOKEN[sensor]="$SENSOR_DIR/main.py"
  USE_SETSID=0
  command_exists setsid && USE_SETSID=1
}

refresh_runtime_environment() {
  BACKEND_URL="http://127.0.0.1:${FINAL_BACKEND_PORT}"
  FRONTEND_URL="http://127.0.0.1:${FINAL_FRONTEND_PORT}"

  export SESSION_UUID
  export FINAL_BACKEND_PORT
  export FINAL_FRONTEND_PORT
  export BACKEND_PORT="$FINAL_BACKEND_PORT"
  export FRONTEND_PORT="$FINAL_FRONTEND_PORT"
  export FLASK_PORT="$FINAL_BACKEND_PORT"
  export PORT="$FINAL_FRONTEND_PORT"
  export BACKEND_URL
  export NEXT_PUBLIC_API_URL="$BACKEND_URL"
  export NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL"
  export ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR"
  export ZEINAGUARD_LOCK_FILE="$LOCK_FILE"
  export ZEINAGUARD_SUPERVISOR_PID="$$"
}

write_lock_file() {
  cat >"$LOCK_FILE" <<EOF
session_uuid=${SESSION_UUID}
start_timestamp=${SESSION_STARTED_AT}
backend_port=${FINAL_BACKEND_PORT}
frontend_port=${FINAL_FRONTEND_PORT}
EOF
}

remove_lock_file() {
  rm -f "$LOCK_FILE"
}

pid_file_path() {
  printf '%s/%s.pid\n' "$PID_DIR" "$1"
}

write_pid_file() {
  local service="$1"
  local file
  file="$(pid_file_path "$service")"
  cat >"$file" <<EOF
pid=${SERVICE_PID[$service]}
pgid=${SERVICE_PGID[$service]}
port=${SERVICE_PORT[$service]}
start_time=${SERVICE_STARTED_AT[$service]}
session_uuid=${SESSION_UUID}
EOF
}

remove_pid_file() {
  rm -f "$(pid_file_path "$1")"
}

read_pid_file() {
  local service="$1"
  local __pid_var="$2"
  local __port_var="$3"
  local file
  local pid=""
  local port=""
  local key=""
  local value=""

  file="$(pid_file_path "$service")"
  [ -f "$file" ] || return 1

  while IFS='=' read -r key value; do
    case "$key" in
      pid) pid="$value" ;;
      port) port="$value" ;;
    esac
  done <"$file"

  printf -v "$__pid_var" '%s' "$pid"
  printf -v "$__port_var" '%s' "$port"
  [ -n "$pid" ]
}

pid_is_alive() {
  local pid="${1:-}"
  is_numeric "$pid" || return 1
  kill -0 "$pid" >/dev/null 2>&1
}

ps_user_for_pid() {
  ps -p "$1" -o user= 2>/dev/null | awk '{$1=$1; print}'
}

ps_cmd_for_pid() {
  ps -p "$1" -o args= 2>/dev/null | sed 's/^[[:space:]]*//'
}

ps_summary_for_pid() {
  ps -p "$1" -o pid=,user=,args= 2>/dev/null | sed 's/^[[:space:]]*//'
}

pgid_for_pid() {
  ps -p "$1" -o pgid= 2>/dev/null | awk '{$1=$1; print}'
}

pid_matches_service() {
  local service="$1"
  local pid="$2"
  local user=""
  local cmd=""

  pid_is_alive "$pid" || return 1
  user="$(ps_user_for_pid "$pid")"
  cmd="$(ps_cmd_for_pid "$pid")"

  [ -n "$user" ] || return 1
  [ -n "$cmd" ] || return 1
  [ "$user" = "$CURRENT_USER_NAME" ] || return 1

  case "$service" in
    backend)
      [[ "$cmd" == *"$BACKEND_DIR/app.py"* ]] || [[ "$cmd" == *"${SERVICE_MATCH_TOKEN[$service]}"* ]]
      ;;
    frontend)
      [[ "$cmd" == *"$FRONTEND_NEXT_BIN"* ]] || [[ "$cmd" == *"next dev"* ]] || [[ "$cmd" == *"${SERVICE_MATCH_TOKEN[$service]}"* ]]
      ;;
    sensor)
      [[ "$cmd" == *"$SENSOR_DIR/main.py"* ]] || [[ "$cmd" == *"${SERVICE_MATCH_TOKEN[$service]}"* ]]
      ;;
    *)
      return 1
      ;;
  esac
}

listener_pids_for_port() {
  local port="$1"

  if command_exists ss; then
    ss -ltnpH "( sport = :$port )" 2>/dev/null | grep -o 'pid=[0-9]\+' | cut -d= -f2 | sort -u || true
    return
  fi

  if command_exists lsof; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
    return
  fi

  if command_exists fuser; then
    fuser -n tcp "$port" 2>/dev/null | tr ' ' '\n' | sed '/^$/d' | sort -u || true
  fi
}

port_is_free() {
  [ -z "$(listener_pids_for_port "$1")" ]
}

recent_log_excerpt() {
  local file="$1"
  local lines="${2:-25}"
  [ -f "$file" ] || return 0
  tail -n "$lines" "$file" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//'
}

stop_pid_and_group() {
  local service="$1"
  local pid="$2"
  local reason="$3"
  local pgid=""
  local waited=0

  pid_is_alive "$pid" || {
    remove_pid_file "$service"
    return 0
  }

  pgid="$(pgid_for_pid "$pid")"
  service_log_event "$service" "stop-requested" "$reason"

  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry-run: would stop $service pid=$pid pgid=${pgid:-unknown} reason=$reason"
    return 0
  fi

  if is_numeric "$pgid" && [ "$pgid" -gt 1 ]; then
    kill -TERM -- "-$pgid" >/dev/null 2>&1 || true
  fi
  kill -TERM "$pid" >/dev/null 2>&1 || true

  while pid_is_alive "$pid" && [ "$waited" -lt 8 ]; do
    sleep 1
    waited=$((waited + 1))
  done

  if pid_is_alive "$pid"; then
    if is_numeric "$pgid" && [ "$pgid" -gt 1 ]; then
      kill -KILL -- "-$pgid" >/dev/null 2>&1 || true
    fi
    kill -KILL "$pid" >/dev/null 2>&1 || true
    sleep 1
  fi

  SERVICE_PID["$service"]=""
  SERVICE_PGID["$service"]=""
  remove_pid_file "$service"
  service_log_event "$service" "stopped" "$reason"
}

reconcile_pid_file() {
  local service="$1"
  local reason="$2"
  local pid=""
  local port=""

  if ! read_pid_file "$service" pid port; then
    return 0
  fi

  if pid_matches_service "$service" "$pid"; then
    SERVICE_PID["$service"]="$pid"
    SERVICE_PORT["$service"]="${port:-${SERVICE_PORT[$service]}}"
    stop_pid_and_group "$service" "$pid" "$reason"
    return 0
  fi

  warn_throttled "stale-pid-$service" "Ignoring stale or reused PID for $service: ${pid:-unknown}"
  remove_pid_file "$service"
}

try_reclaim_port() {
  local service="$1"
  local port="$2"
  local pids=""
  local pid=""

  pids="$(listener_pids_for_port "$port")"
  [ -n "$pids" ] || return 0

  while read -r pid; do
    [ -n "$pid" ] || continue
    if pid_matches_service "$service" "$pid"; then
      SERVICE_PID["$service"]="$pid"
      SERVICE_PORT["$service"]="$port"
      stop_pid_and_group "$service" "$pid" "freeing port $port before restart"
    else
      warn_throttled "external-port-$service-$port" "Port $port is busy by another process: $(ps_summary_for_pid "$pid" || printf 'pid=%s' "$pid"). Trying next port."
      return 1
    fi
  done <<<"$pids"

  sleep 1
  port_is_free "$port"
}

allocate_port() {
  local service="$1"
  local requested_port="$2"
  local __result_var="$3"
  local offset=0
  local candidate=0

  while [ "$offset" -lt "$PORT_FALLBACK_COUNT" ]; do
    candidate=$((requested_port + offset))

    if port_is_free "$candidate"; then
      printf -v "$__result_var" '%s' "$candidate"
      return 0
    fi

    if try_reclaim_port "$service" "$candidate"; then
      printf -v "$__result_var" '%s' "$candidate"
      return 0
    fi

    offset=$((offset + 1))
  done

  return 1
}

http_check() {
  local url="$1"
  local expected_key="${2:-}"
  local expected_value="${3:-}"

  python3 - "$url" "$expected_key" "$expected_value" <<'PY'
import json
import sys
import urllib.request

url = sys.argv[1]
expected_key = sys.argv[2]
expected_value = sys.argv[3]

try:
    with urllib.request.urlopen(url, timeout=2) as response:
        body = response.read().decode("utf-8", errors="replace")
        if not (200 <= response.status < 300):
            raise SystemExit(1)
        if not expected_key:
            raise SystemExit(0)
        payload = json.loads(body)
        raise SystemExit(0 if str(payload.get(expected_key, "")) == expected_value else 1)
except Exception:
    raise SystemExit(1)
PY
}

wait_for_http() {
  local url="$1"
  local timeout_seconds="$2"
  local expected_key="${3:-}"
  local expected_value="${4:-}"
  local deadline=$((SECONDS + timeout_seconds))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if http_check "$url" "$expected_key" "$expected_value"; then
      return 0
    fi
    sleep 1
  done

  return 1
}

backend_healthy() {
  http_check "$BACKEND_URL/health" status healthy
}

frontend_healthy() {
  http_check "$FRONTEND_URL"
}

interface_exists() {
  local interface_name="$1"
  [ -n "$interface_name" ] || return 1
  [ -d "/sys/class/net/$interface_name" ] && return 0
  command_exists ip && ip link show "$interface_name" >/dev/null 2>&1 && return 0
  command_exists ifconfig && ifconfig "$interface_name" >/dev/null 2>&1 && return 0
  return 1
}

discover_interfaces() {
  if [ -d /sys/class/net ]; then
    find /sys/class/net -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null
    return
  fi

  if command_exists ip; then
    ip -o link show 2>/dev/null | awk -F': ' '{print $2}'
  fi
}

select_sensor_interface() {
  local candidate=""

  if [ -n "${SENSOR_INTERFACE:-}" ] && interface_exists "$SENSOR_INTERFACE"; then
    SELECTED_SENSOR_INTERFACE="$SENSOR_INTERFACE"
    return 0
  fi

  while read -r candidate; do
    [ -n "$candidate" ] || continue
    if interface_exists "$candidate"; then
      SELECTED_SENSOR_INTERFACE="$candidate"
      return 0
    fi
  done < <(discover_interfaces)

  return 1
}

disable_sensor() {
  local reason="$1"
  SENSOR_DISABLED=1
  SENSOR_DISABLE_REASON="$reason"
  service_log_event "sensor" "disabled" "$reason"
  warn "Sensor disabled: $reason"

  if [ -n "${SERVICE_PID[sensor]:-}" ] && pid_is_alive "${SERVICE_PID[sensor]}"; then
    stop_pid_and_group "sensor" "${SERVICE_PID[sensor]}" "$reason"
  else
    remove_pid_file "sensor"
  fi
}

sensor_dry_run_command() {
  if [ -n "${ZEINAGUARD_SENSOR_CMD_OVERRIDE:-}" ]; then
    sudo -n env \
      ZEINAGUARD_SESSION_UUID="${SESSION_UUID:-preflight}" \
      ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
      ZEINAGUARD_SERVICE="sensor" \
      BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${REQUESTED_BACKEND_PORT:-5000}}" \
      SENSOR_INTERFACE="${SELECTED_SENSOR_INTERFACE:-${SENSOR_INTERFACE:-}}" \
      SENSOR_LOG_FILE="$SENSOR_LOG" \
      bash -lc "${ZEINAGUARD_SENSOR_CMD_OVERRIDE} --dry-run"
    return
  fi

  sudo -n env \
    ZEINAGUARD_SESSION_UUID="${SESSION_UUID:-preflight}" \
    ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
    ZEINAGUARD_SERVICE="sensor" \
    BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:${REQUESTED_BACKEND_PORT:-5000}}" \
    SENSOR_INTERFACE="${SELECTED_SENSOR_INTERFACE:-${SENSOR_INTERFACE:-}}" \
    SENSOR_LOG_FILE="$SENSOR_LOG" \
    "$SENSOR_PYTHON" "$SENSOR_DIR/main.py" --dry-run
}

validate_sensor_sudo() {
  local output=""
  local status=0

  output="$(sensor_dry_run_command 2>&1)" || status=$?

  if [ "$status" -eq 0 ]; then
    [ -n "$output" ] && printf '%s\n' "$output" >>"$SENSOR_LOG"
    return 0
  fi

  [ -n "$output" ] && printf '%s\n' "$output" >>"$SENSOR_LOG"
  if printf '%s' "$output" | grep -qi 'password .*required'; then
    disable_sensor "sudo dry-run failed; sensor will stay optional"
  else
    disable_sensor "sensor dry-run failed: ${output:-unknown error}"
  fi
  return 1
}

ensure_frontend_dependencies() {
  if [ -n "${ZEINAGUARD_FRONTEND_CMD_OVERRIDE:-}" ]; then
    return 0
  fi

  if [ -x "$FRONTEND_NEXT_BIN" ]; then
    return 0
  fi

  if [ "${ZEINAGUARD_SKIP_FRONTEND_INSTALL:-0}" = "1" ]; then
    return 1
  fi

  if command_exists pnpm; then
    log "Frontend dependencies missing; running pnpm install"
    (
      cd "$FRONTEND_DIR" &&
      pnpm install >>"$FRONTEND_LOG" 2>&1
    ) || return 1
  elif command_exists npm; then
    log "Frontend dependencies missing; running npm install"
    (
      cd "$FRONTEND_DIR" &&
      npm install >>"$FRONTEND_LOG" 2>&1
    ) || return 1
  else
    return 1
  fi

  [ -x "$FRONTEND_NEXT_BIN" ]
}

run_preflight_checks() {
  local errors=()

  if ! command_exists python3; then
    errors+=("python3 is required")
  fi

  if ! command_exists ps; then
    errors+=("ps is required for safe PID validation")
  fi

  if [ -z "${ZEINAGUARD_BACKEND_CMD_OVERRIDE:-}" ] && [ ! -f "$BACKEND_DIR/app.py" ]; then
    errors+=("backend entrypoint is missing: $BACKEND_DIR/app.py")
  fi

  if [ -z "${ZEINAGUARD_FRONTEND_CMD_OVERRIDE:-}" ] && [ ! -f "$FRONTEND_DIR/package.json" ]; then
    errors+=("frontend package manifest is missing: $FRONTEND_DIR/package.json")
  fi

  if [ -z "${ZEINAGUARD_FRONTEND_CMD_OVERRIDE:-}" ] && ! command_exists node; then
    errors+=("node is required for the frontend")
  fi

  if [ -z "${ZEINAGUARD_BACKEND_CMD_OVERRIDE:-}" ] && ! command_exists "$BACKEND_PYTHON"; then
    errors+=("backend Python is unavailable: $BACKEND_PYTHON")
  fi

  if ! ensure_frontend_dependencies; then
    errors+=("frontend runtime is unavailable: $FRONTEND_NEXT_BIN")
  fi

  if [ "${#errors[@]}" -gt 0 ]; then
    local item=""
    for item in "${errors[@]}"; do
      error_log "$item"
    done
    return 1
  fi

  SENSOR_DISABLED=0
  SENSOR_DISABLE_REASON=""

  if [ ! -f "$SENSOR_DIR/main.py" ] && [ -z "${ZEINAGUARD_SENSOR_CMD_OVERRIDE:-}" ]; then
    disable_sensor "sensor entrypoint missing"
    return 0
  fi

  if ! command_exists sudo; then
    disable_sensor "sudo is unavailable"
    return 0
  fi

  if ! select_sensor_interface; then
    disable_sensor "no network interface found for sensor startup"
    return 0
  fi

  validate_sensor_sudo || true
  return 0
}

start_service_process() {
  local service="$1"
  local workdir="$2"
  local log_file="$3"
  local port="$4"
  shift 4

  local pid=""
  local pgid=""

  SERVICE_PORT["$service"]="$port"
  SERVICE_STARTED_AT["$service"]="$(timestamp)"
  service_log_event "$service" "start-requested" "starting service"

  if [ "$DRY_RUN" -eq 1 ]; then
    log "Dry-run: would start $service on port $port"
    return 0
  fi

  (
    cd "$workdir" || exit 1
    if [ "$USE_SETSID" -eq 1 ]; then
      exec env \
        ZEINAGUARD_SESSION_UUID="$SESSION_UUID" \
        ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
        ZEINAGUARD_LOCK_FILE="$LOCK_FILE" \
        ZEINAGUARD_SERVICE="$service" \
        BACKEND_URL="$BACKEND_URL" \
        SENSOR_INTERFACE="${SELECTED_SENSOR_INTERFACE:-}" \
        SENSOR_LOG_FILE="$SENSOR_LOG" \
        BACKEND_PORT="$FINAL_BACKEND_PORT" \
        FRONTEND_PORT="$FINAL_FRONTEND_PORT" \
        FLASK_PORT="$FINAL_BACKEND_PORT" \
        PORT="$FINAL_FRONTEND_PORT" \
        NEXT_PUBLIC_API_URL="$BACKEND_URL" \
        NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL" \
        setsid "$@" >>"$log_file" 2>&1
    else
      exec env \
        ZEINAGUARD_SESSION_UUID="$SESSION_UUID" \
        ZEINAGUARD_PROJECT_ROOT="$ROOT_DIR" \
        ZEINAGUARD_LOCK_FILE="$LOCK_FILE" \
        ZEINAGUARD_SERVICE="$service" \
        BACKEND_URL="$BACKEND_URL" \
        SENSOR_INTERFACE="${SELECTED_SENSOR_INTERFACE:-}" \
        SENSOR_LOG_FILE="$SENSOR_LOG" \
        BACKEND_PORT="$FINAL_BACKEND_PORT" \
        FRONTEND_PORT="$FINAL_FRONTEND_PORT" \
        FLASK_PORT="$FINAL_BACKEND_PORT" \
        PORT="$FINAL_FRONTEND_PORT" \
        NEXT_PUBLIC_API_URL="$BACKEND_URL" \
        NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL" \
        "$@" >>"$log_file" 2>&1
    fi
  ) &

  pid=$!
  sleep 1

  if ! pid_is_alive "$pid"; then
    SERVICE_PID["$service"]=""
    SERVICE_PGID["$service"]=""
    service_log_event "$service" "startup-failed" "$(recent_log_excerpt "$log_file" 30)"
    return 1
  fi

  pgid="$(pgid_for_pid "$pid")"
  [ -n "$pgid" ] || pgid="$pid"

  SERVICE_PID["$service"]="$pid"
  SERVICE_PGID["$service"]="$pgid"
  write_pid_file "$service"
  service_log_event "$service" "started" "service running"
  log "$service started pid=$pid port=$port"
  return 0
}

launch_backend() {
  if [ -n "${ZEINAGUARD_BACKEND_CMD_OVERRIDE:-}" ]; then
    start_service_process "backend" "$BACKEND_DIR" "$BACKEND_LOG" "$FINAL_BACKEND_PORT" bash -lc "$ZEINAGUARD_BACKEND_CMD_OVERRIDE"
    return
  fi

  start_service_process "backend" "$BACKEND_DIR" "$BACKEND_LOG" "$FINAL_BACKEND_PORT" "$BACKEND_PYTHON" "$BACKEND_DIR/app.py"
}

launch_frontend() {
  if [ -n "${ZEINAGUARD_FRONTEND_CMD_OVERRIDE:-}" ]; then
    start_service_process "frontend" "$FRONTEND_DIR" "$FRONTEND_LOG" "$FINAL_FRONTEND_PORT" bash -lc "$ZEINAGUARD_FRONTEND_CMD_OVERRIDE"
    return
  fi

  start_service_process "frontend" "$FRONTEND_DIR" "$FRONTEND_LOG" "$FINAL_FRONTEND_PORT" "$FRONTEND_NEXT_BIN" dev --port "$FINAL_FRONTEND_PORT" --hostname 0.0.0.0
}

launch_sensor_once() {
  if [ "$SENSOR_DISABLED" -eq 1 ]; then
    return 0
  fi

  if [ -n "${ZEINAGUARD_SENSOR_CMD_OVERRIDE:-}" ]; then
    start_service_process "sensor" "$SENSOR_DIR" "$SENSOR_LOG" "n/a" sudo -n env SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" SENSOR_LOG_FILE="$SENSOR_LOG" BACKEND_URL="$BACKEND_URL" bash -lc "$ZEINAGUARD_SENSOR_CMD_OVERRIDE"
    return
  fi

  start_service_process "sensor" "$SENSOR_DIR" "$SENSOR_LOG" "n/a" sudo -n env SENSOR_INTERFACE="$SELECTED_SENSOR_INTERFACE" SENSOR_LOG_FILE="$SENSOR_LOG" BACKEND_URL="$BACKEND_URL" "$SENSOR_PYTHON" "$SENSOR_DIR/main.py"
}

start_sensor_service() {
  local failure_reason=""

  if [ "$SENSOR_DISABLED" -eq 1 ]; then
    return 0
  fi

  if launch_sensor_once; then
    return 0
  fi

  failure_reason="$(recent_log_excerpt "$SENSOR_LOG" 30)"
  if printf '%s' "$failure_reason" | grep -qi 'password .*required'; then
    disable_sensor "sudo launch failed; sensor disabled without blocking stack"
    return 0
  fi

  if [ "$SENSOR_RETRY_COUNT" -lt "$SENSOR_MAX_RETRIES" ]; then
    SENSOR_RETRY_COUNT=$((SENSOR_RETRY_COUNT + 1))
    sleep 2
    if launch_sensor_once; then
      return 0
    fi
    failure_reason="$(recent_log_excerpt "$SENSOR_LOG" 30)"
  fi

  disable_sensor "sensor failed after one retry: ${failure_reason:-unknown error}"
  return 0
}

reconcile_existing_runtime() {
  reconcile_pid_file "sensor" "preflight cleanup"
  reconcile_pid_file "frontend" "preflight cleanup"
  reconcile_pid_file "backend" "preflight cleanup"

  if [ -f "$LOCK_FILE" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      log "Dry-run: found existing lock file at $LOCK_FILE"
    else
      rm -f "$LOCK_FILE"
    fi
  fi
}

print_summary() {
  local sensor_state="running"
  [ "$SENSOR_DISABLED" -eq 1 ] && sensor_state="disabled"

  cat <<EOF
ZeinaGuard is running
Session UUID : ${SESSION_UUID}
Frontend URL : ${FRONTEND_URL}
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
Backend URL  : http://127.0.0.1:${FINAL_BACKEND_PORT}
Sensor       : $([ "$SENSOR_DISABLED" -eq 1 ] && printf 'disabled' || printf 'ready')
EOF
}

shutdown_all() {
  local exit_code="${1:-0}"

  if [ "$SHUTDOWN_DONE" -eq 1 ]; then
    return
  fi
  SHUTDOWN_DONE=1
  SHUTDOWN_REQUESTED=1

  if [ -n "${SERVICE_PID[sensor]:-}" ]; then
    stop_pid_and_group "sensor" "${SERVICE_PID[sensor]}" "supervisor shutdown"
  else
    reconcile_pid_file "sensor" "supervisor shutdown"
  fi

  if [ -n "${SERVICE_PID[frontend]:-}" ]; then
    stop_pid_and_group "frontend" "${SERVICE_PID[frontend]}" "supervisor shutdown"
  else
    reconcile_pid_file "frontend" "supervisor shutdown"
  fi

  if [ -n "${SERVICE_PID[backend]:-}" ]; then
    stop_pid_and_group "backend" "${SERVICE_PID[backend]}" "supervisor shutdown"
  else
    reconcile_pid_file "backend" "supervisor shutdown"
  fi

  if [ "$DRY_RUN" -eq 0 ]; then
    remove_lock_file
  fi
  flush_throttled_warnings

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
    error_log "Lifecycle supervisor exiting with failure"
  fi

  shutdown_all "$exit_code"
}

supervisor_fail() {
  error_log "$1"
  exit 1
}

monitor_services() {
  local backend_failures=0
  local frontend_failures=0
  local reason=""

  while [ "$SHUTDOWN_REQUESTED" -eq 0 ]; do
    if backend_healthy; then
      backend_failures=0
    else
      backend_failures=$((backend_failures + 1))
      warn_throttled "backend-health" "Backend health check failed (${backend_failures}/3)"
      if [ "$backend_failures" -ge 3 ]; then
        reason="$(recent_log_excerpt "$BACKEND_LOG" 30)"
        service_log_event "backend" "health-failed" "$reason"
        supervisor_fail "Backend became unhealthy. See $BACKEND_LOG"
      fi
    fi

    if frontend_healthy; then
      frontend_failures=0
    else
      frontend_failures=$((frontend_failures + 1))
      warn_throttled "frontend-health" "Frontend health check failed (${frontend_failures}/3)"
      if [ "$frontend_failures" -ge 3 ]; then
        reason="$(recent_log_excerpt "$FRONTEND_LOG" 30)"
        service_log_event "frontend" "health-failed" "$reason"
        supervisor_fail "Frontend became unhealthy. See $FRONTEND_LOG"
      fi
    fi

    if [ "$SENSOR_DISABLED" -eq 0 ] && [ -n "${SERVICE_PID[sensor]:-}" ] && ! pid_is_alive "${SERVICE_PID[sensor]}"; then
      reason="$(recent_log_excerpt "$SENSOR_LOG" 30)"
      if [ "$SENSOR_RETRY_COUNT" -lt "$SENSOR_MAX_RETRIES" ]; then
        SENSOR_RETRY_COUNT=$((SENSOR_RETRY_COUNT + 1))
        warn_throttled "sensor-restart" "Sensor exited; retrying once"
        sleep 2
        if ! launch_sensor_once; then
          reason="$(recent_log_excerpt "$SENSOR_LOG" 30)"
          disable_sensor "sensor stopped after one retry: ${reason:-unknown error}"
        fi
      else
        disable_sensor "sensor stopped and was left disabled: ${reason:-unknown error}"
      fi
    fi

    sleep "$MONITOR_INTERVAL"
  done
}

run_stack() {
  trap on_interrupt INT TERM
  trap on_exit EXIT

  load_env_file
  refresh_config
  ensure_runtime_dirs
  prepare_log_files

  SESSION_UUID="$(generate_uuid)"
  SESSION_STARTED_AT="$(timestamp)"

  run_preflight_checks || exit 1
  reconcile_existing_runtime

  allocate_port "backend" "$REQUESTED_BACKEND_PORT" FINAL_BACKEND_PORT || supervisor_fail "No backend port available in ${REQUESTED_BACKEND_PORT}-$((REQUESTED_BACKEND_PORT + PORT_FALLBACK_COUNT - 1))"
  allocate_port "frontend" "$REQUESTED_FRONTEND_PORT" FINAL_FRONTEND_PORT || supervisor_fail "No frontend port available in ${REQUESTED_FRONTEND_PORT}-$((REQUESTED_FRONTEND_PORT + PORT_FALLBACK_COUNT - 1))"
  refresh_runtime_environment

  if [ "$DRY_RUN" -eq 1 ]; then
    print_dry_run_summary
    return 0
  fi

  write_lock_file

  log "Starting backend on port $FINAL_BACKEND_PORT"
  launch_backend || supervisor_fail "backend failed to stay running. See $BACKEND_LOG"
  wait_for_http "$BACKEND_URL/health" "$BACKEND_HEALTH_TIMEOUT" status healthy || supervisor_fail "backend did not become healthy. See $BACKEND_LOG"
  service_log_event "backend" "health-passed" "HTTP /health passed"

  log "Starting frontend on port $FINAL_FRONTEND_PORT"
  launch_frontend || supervisor_fail "frontend failed to stay running. See $FRONTEND_LOG"
  wait_for_http "$FRONTEND_URL" "$FRONTEND_HEALTH_TIMEOUT" || supervisor_fail "frontend did not become reachable. See $FRONTEND_LOG"
  service_log_event "frontend" "health-passed" "HTTP frontend check passed"

  log "Starting sensor"
  start_sensor_service

  print_summary
  monitor_services
}

test_assert_contains() {
  local file="$1"
  local pattern="$2"
  grep -Fq "$pattern" "$file"
}

test_wait_for_pattern() {
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

test_make_sudo_stub() {
  local stub_dir="$1"
  cat >"$stub_dir/sudo" <<'EOF'
#!/usr/bin/env bash
set -eu
mode="${ZEINAGUARD_TEST_SUDO_MODE:-success}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    -n|-E)
      shift
      ;;
    env)
      shift
      while [ "$#" -gt 0 ] && printf '%s' "$1" | grep -q '='; do
        export "$1"
        shift
      done
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
  chmod +x "$stub_dir/sudo"

  cat >"$stub_dir/python3" <<'EOF'
#!/usr/bin/env bash
exec python "$@"
EOF
  chmod +x "$stub_dir/python3"
}

test_make_mock_service() {
  local file="$1"
  cat >"$file" <<'EOF'
#!/usr/bin/env python3
import json
import signal
import socketserver
import sys
import time
from http.server import BaseHTTPRequestHandler

service = sys.argv[1]
mode = sys.argv[2]
port = int(sys.argv[3]) if len(sys.argv) > 3 else 0

stop = False

def handle_signal(_signum, _frame):
    global stop
    stop = True

signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

if mode == "crash":
    time.sleep(1)
    sys.exit(1)

if service == "sensor":
    if "--dry-run" in sys.argv:
        print("[mock-sensor] dry-run ok", flush=True)
        sys.exit(0)
    while not stop:
        time.sleep(1)
    sys.exit(0)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if service == "backend" and self.path.startswith("/health"):
            body = json.dumps({"status": "healthy"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return

class Server(socketserver.TCPServer):
    allow_reuse_address = True

with Server(("127.0.0.1", port), Handler) as httpd:
    httpd.timeout = 1
    while not stop:
        httpd.handle_request()
EOF
  chmod +x "$file"
}

test_service_override() {
  local service="$1"
  local mode="$2"
  local mock_file="$3"

  case "$service" in
    backend)
      printf "exec -a '%s' python3 '%s' backend %s \"\$BACKEND_PORT\"" "$BACKEND_DIR/app.py" "$mock_file" "$mode"
      ;;
    frontend)
      printf "exec -a '%s' python3 '%s' frontend %s \"\$FRONTEND_PORT\"" "$FRONTEND_NEXT_BIN" "$mock_file" "$mode"
      ;;
    sensor)
      printf "exec -a '%s' python3 '%s' sensor %s" "$SENSOR_DIR/main.py" "$mock_file" "$mode"
      ;;
  esac
}

test_setup_case_env() {
  local case_root="$1"
  local stub_dir="$2"
  local mock_file="$3"

  export ZEINAGUARD_IGNORE_ENV_FILE=1
  export ZEINAGUARD_RUNTIME_DIR="$case_root/runtime"
  export ZEINAGUARD_LOG_DIR="$case_root/logs"
  export ZEINAGUARD_LOCK_FILE="$case_root/zeinaguard.lock"
  export ZEINAGUARD_SKIP_FRONTEND_INSTALL=1
  export ZEINAGUARD_BACKEND_CMD_OVERRIDE="$(test_service_override backend stable "$mock_file")"
  export ZEINAGUARD_FRONTEND_CMD_OVERRIDE="$(test_service_override frontend stable "$mock_file")"
  export ZEINAGUARD_SENSOR_CMD_OVERRIDE="$(test_service_override sensor stable "$mock_file")"
  export SENSOR_INTERFACE="lo"
  export PATH="$stub_dir:$PATH"
  export ZEINAGUARD_TEST_SUDO_MODE="success"
}

test_run_background() {
  local output_file="$1"
  (
    cd "$ROOT_DIR" &&
    ./run.sh
  ) >"$output_file" 2>&1 &
  printf '%s\n' "$!"
}

test_start_external_listener() {
  local port="$1"
  local log_file="$2"
  python3 -m http.server "$port" --bind 127.0.0.1 >"$log_file" 2>&1 &
  printf '%s\n' "$!"
}

run_self_tests() {
  local tmp_root=""
  local stub_dir=""
  local mock_file=""
  local output_file=""
  local run_pid=""
  local listener_pid=""
  local listener_pid2=""
  local failures=0
  local passes=0
  local capture_file=""

  test_print_result() {
    local name="$1"
    local status="$2"
    local details="$3"
    printf '%s: %s%s\n' "$name" "$status" "$([ -n "$details" ] && printf ' - %s' "$details")"
  }

  case "$(uname -s)" in
    Linux*|MINGW*|MSYS*)
      ;;
    *)
      printf 'run.sh --test: FAIL - unsupported runtime for supervisor simulation\n'
      return 1
      ;;
  esac

  tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/zeinaguard-selftest.XXXXXX")"
  stub_dir="$tmp_root/bin"
  mock_file="$tmp_root/mock_service.py"
  mkdir -p "$stub_dir"

  test_make_sudo_stub "$stub_dir"
  test_make_mock_service "$mock_file"

  cleanup_test_case() {
    [ -n "${run_pid:-}" ] && kill -INT "$run_pid" >/dev/null 2>&1 || true
    [ -n "${listener_pid:-}" ] && kill -TERM "$listener_pid" >/dev/null 2>&1 || true
    [ -n "${listener_pid2:-}" ] && kill -TERM "$listener_pid2" >/dev/null 2>&1 || true
    run_pid=""
    listener_pid=""
    listener_pid2=""
    unset ZEINAGUARD_IGNORE_ENV_FILE ZEINAGUARD_RUNTIME_DIR ZEINAGUARD_LOG_DIR ZEINAGUARD_LOCK_FILE
    unset ZEINAGUARD_SKIP_FRONTEND_INSTALL ZEINAGUARD_BACKEND_CMD_OVERRIDE ZEINAGUARD_FRONTEND_CMD_OVERRIDE
    unset ZEINAGUARD_SENSOR_CMD_OVERRIDE SENSOR_INTERFACE ZEINAGUARD_TEST_SUDO_MODE
  }

  trap 'cleanup_test_case; rm -rf "$tmp_root"' RETURN

  test_case_sudo_failure() {
    local case_root="$tmp_root/sudo-failure"
    mkdir -p "$case_root"
    test_setup_case_env "$case_root" "$stub_dir" "$mock_file"
    export ZEINAGUARD_TEST_SUDO_MODE="fail"
    output_file="$case_root/output.log"
    run_pid="$(test_run_background "$output_file")"
    if test_wait_for_pattern "$output_file" "ZeinaGuard is running" 25 && test_assert_contains "$output_file" "Sensor       : disabled"; then
      kill -INT "$run_pid" >/dev/null 2>&1 || true
      wait "$run_pid" >/dev/null 2>&1 || true
      passes=$((passes + 1))
      test_print_result "sudo failure -> system continues" "PASS" ""
    else
      failures=$((failures + 1))
      test_print_result "sudo failure -> system continues" "FAIL" "$(recent_log_excerpt "$output_file" 40)"
    fi
    cleanup_test_case
  }

  test_case_port_conflict() {
    local case_root="$tmp_root/port-conflict"
    mkdir -p "$case_root"
    test_setup_case_env "$case_root" "$stub_dir" "$mock_file"
    output_file="$case_root/output.log"
    listener_pid="$(test_start_external_listener 3000 "$case_root/listener-3000.log")"
    listener_pid2="$(test_start_external_listener 5000 "$case_root/listener-5000.log")"
    sleep 1
    run_pid="$(test_run_background "$output_file")"
    if test_wait_for_pattern "$output_file" "ZeinaGuard is running" 25 && test_assert_contains "$output_file" "Frontend URL : http://127.0.0.1:3001" && test_assert_contains "$output_file" "Backend URL  : http://127.0.0.1:5001"; then
      kill -INT "$run_pid" >/dev/null 2>&1 || true
      wait "$run_pid" >/dev/null 2>&1 || true
      passes=$((passes + 1))
      test_print_result "port 3000/5000 busy -> fallback works" "PASS" ""
    else
      failures=$((failures + 1))
      test_print_result "port 3000/5000 busy -> fallback works" "FAIL" "$(recent_log_excerpt "$output_file" 40)"
    fi
    cleanup_test_case
  }

  test_case_sensor_crash() {
    local case_root="$tmp_root/sensor-crash"
    mkdir -p "$case_root"
    test_setup_case_env "$case_root" "$stub_dir" "$mock_file"
    export ZEINAGUARD_SENSOR_CMD_OVERRIDE="$(test_service_override sensor crash "$mock_file")"
    output_file="$case_root/output.log"
    run_pid="$(test_run_background "$output_file")"
    if test_wait_for_pattern "$output_file" "ZeinaGuard is running" 25 && test_assert_contains "$output_file" "Sensor       : disabled" && kill -0 "$run_pid" >/dev/null 2>&1; then
      kill -INT "$run_pid" >/dev/null 2>&1 || true
      wait "$run_pid" >/dev/null 2>&1 || true
      passes=$((passes + 1))
      test_print_result "sensor crash -> system continues" "PASS" ""
    else
      failures=$((failures + 1))
      test_print_result "sensor crash -> system continues" "FAIL" "$(recent_log_excerpt "$output_file" 40)"
    fi
    cleanup_test_case
  }

  test_case_stale_pid() {
    local case_root="$tmp_root/stale-pid"
    mkdir -p "$case_root/runtime/pids"
    test_setup_case_env "$case_root" "$stub_dir" "$mock_file"
    output_file="$case_root/output.log"
    cat >"$case_root/runtime/pids/backend.pid" <<EOF
pid=999999
pgid=999999
port=5000
start_time=$(timestamp)
session_uuid=stale
EOF
    run_pid="$(test_run_background "$output_file")"
    if test_wait_for_pattern "$output_file" "ZeinaGuard is running" 25; then
      kill -INT "$run_pid" >/dev/null 2>&1 || true
      wait "$run_pid" >/dev/null 2>&1 || true
      passes=$((passes + 1))
      test_print_result "stale PID -> ignored safely" "PASS" ""
    else
      failures=$((failures + 1))
      test_print_result "stale PID -> ignored safely" "FAIL" "$(recent_log_excerpt "$output_file" 40)"
    fi
    cleanup_test_case
  }

  test_case_backend_health_source() {
    local case_root="$tmp_root/backend-health"
    mkdir -p "$case_root"
    test_setup_case_env "$case_root" "$stub_dir" "$mock_file"
    output_file="$case_root/output.log"
    run_pid="$(test_run_background "$output_file")"
    if test_wait_for_pattern "$output_file" "ZeinaGuard is running" 25; then
      sleep 4
      if kill -0 "$run_pid" >/dev/null 2>&1 && ! grep -Fq "Backend became unhealthy" "$output_file"; then
        kill -INT "$run_pid" >/dev/null 2>&1 || true
        wait "$run_pid" >/dev/null 2>&1 || true
        passes=$((passes + 1))
        test_print_result "backend healthy -> not marked invalid" "PASS" ""
      else
        failures=$((failures + 1))
        test_print_result "backend healthy -> not marked invalid" "FAIL" "$(recent_log_excerpt "$output_file" 40)"
      fi
    else
      failures=$((failures + 1))
      test_print_result "backend healthy -> not marked invalid" "FAIL" "$(recent_log_excerpt "$output_file" 40)"
    fi
    cleanup_test_case
  }

  test_case_warning_suppression() {
    local case_root="$tmp_root/warn-suppression"
    mkdir -p "$case_root"
    capture_file="$case_root/warnings.log"
    exec 3>&2 2>"$capture_file"
    warn_throttled "spam-case" "Skipping external process because fingerprint validation failed"
    warn_throttled "spam-case" "Skipping external process because fingerprint validation failed"
    warn_throttled "spam-case" "Skipping external process because fingerprint validation failed"
    warn_throttled "spam-case" "Skipping external process because fingerprint validation failed"
    warn_throttled "spam-case" "Skipping external process because fingerprint validation failed"
    exec 2>&3 3>&-
    if [ "$(grep -c 'Skipping external process because fingerprint validation failed' "$capture_file" 2>/dev/null || true)" -le 4 ] && grep -Fq 'Suppressing repeated warnings for 10s' "$capture_file"; then
      passes=$((passes + 1))
      test_print_result "repeated warnings -> suppressed" "PASS" ""
    else
      failures=$((failures + 1))
      test_print_result "repeated warnings -> suppressed" "FAIL" "$(recent_log_excerpt "$capture_file" 20)"
    fi
  }

  test_case_sudo_failure
  test_case_port_conflict
  test_case_sensor_crash
  test_case_stale_pid
  test_case_backend_health_source
  test_case_warning_suppression

  printf 'Summary: %s PASS, %s FAIL\n' "$passes" "$failures"
  [ "$failures" -eq 0 ]
}

main() {
  parse_args "$@"

  if [ "$RUN_TESTS" -eq 1 ]; then
    run_self_tests
    return $?
  fi

  run_stack
}

main "$@"
