#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
FRONTEND_DIR="$ROOT_DIR"
BACKEND_DIR="$ROOT_DIR/backend"
SENSOR_DIR="$ROOT_DIR/sensor"
ENV_FILE="$ROOT_DIR/.env"

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"

FRONTEND_LOG="$LOG_DIR/frontend.log"
BACKEND_LOG="$LOG_DIR/backend.log"
SENSOR_LOG="$LOG_DIR/sensor.log"

declare -a START_ORDER=()
declare -A SERVICE_PIDS=()

CLEANUP_DONE=0

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

  # Force a consistent local topology for this supervisor.
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

ensure_pnpm() {
  if command_exists pnpm; then
    return
  fi

  if command_exists corepack; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare pnpm@latest --activate >/dev/null 2>&1 || true
  fi

  command_exists pnpm || fail "pnpm is required to start the frontend"
}

hash_file() {
  local target="$1"

  if command_exists sha256sum; then
    sha256sum "$target" | awk '{print $1}'
    return
  fi

  if command_exists shasum; then
    shasum -a 256 "$target" | awk '{print $1}'
    return
  fi

  python3 - "$target" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

python_in_venv() {
  local python_bin="$1"
  "$python_bin" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else 1)
PY
}

venv_is_valid() {
  local venv_dir="$1"
  local python_bin="$venv_dir/bin/python"

  [ -d "$venv_dir" ] || return 1
  [ -x "$python_bin" ] || return 1
  python_in_venv "$python_bin" || return 1
  "$python_bin" -m pip --version >/dev/null 2>&1 || return 1
  "$python_bin" -m pip check >/dev/null 2>&1 || return 1
}

ensure_python_venv() {
  local service_name="$1"
  local service_dir="$2"
  local requirements_file="$3"
  local venv_dir="$service_dir/.venv"
  local python_bin="$venv_dir/bin/python"
  local stamp_file="$venv_dir/.requirements.sha256"
  local desired_hash=""
  local current_hash=""

  [ -f "$requirements_file" ] || fail "Missing requirements file for $service_name: $requirements_file"

  desired_hash="$(hash_file "$requirements_file")"
  if [ -f "$stamp_file" ]; then
    current_hash="$(tr -d '[:space:]' <"$stamp_file")"
  fi

  if venv_is_valid "$venv_dir" && [ "$desired_hash" = "$current_hash" ]; then
    log "Reusing cached ${service_name} virtual environment"
    return
  fi

  if [ -d "$venv_dir" ] && ! venv_is_valid "$venv_dir"; then
    warn "$service_name virtual environment is invalid; recreating it"
    rm -rf "$venv_dir"
  fi

  if [ ! -d "$venv_dir" ]; then
    log "Creating ${service_name} virtual environment"
    python3 -m venv "$venv_dir"
  else
    log "Refreshing ${service_name} dependencies"
  fi

  log "Installing ${service_name} dependencies"
  "$python_bin" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$python_bin" -m pip install --upgrade pip setuptools wheel >/dev/null
  "$python_bin" -m pip install -r "$requirements_file"
  printf '%s\n' "$desired_hash" >"$stamp_file"
}

ensure_frontend_dependencies() {
  ensure_pnpm

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
    fuser -n tcp "$port" 2>/dev/null || true
    return
  fi

  if command_exists lsof; then
    lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true
    return
  fi

  warn "Neither fuser nor lsof is available for port inspection"
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
  if [ -f "$pid_file" ]; then
    pid="$(tr -d '[:space:]' <"$pid_file" || true)"
    terminate_pid "$pid" "$service_name"
    rm -f "$pid_file"
  fi
}

cleanup_port_if_needed() {
  local port="$1"
  local listeners=""

  listeners="$(port_listeners "$port")"
  [ -n "$listeners" ] || return 0

  warn "Port $port is busy; attempting cleanup"
  if command_exists fuser; then
    fuser -k -TERM -n tcp "$port" >/dev/null 2>&1 || true
    sleep 2
    if [ -n "$(port_listeners "$port")" ]; then
      fuser -k -KILL -n tcp "$port" >/dev/null 2>&1 || true
      sleep 1
    fi
  elif command_exists lsof; then
    while read -r port_pid; do
      [ -n "$port_pid" ] || continue
      kill -TERM "$port_pid" >/dev/null 2>&1 || true
    done <<<"$listeners"
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

require_sudo_access() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    return
  fi

  ensure_command sudo
  if sudo -n true >/dev/null 2>&1; then
    return
  fi

  log "Requesting sudo once for the sensor process"
  sudo -v
}

build_sensor_command() {
  local -n out_command_ref="$1"
  local sensor_shell_command=""
  local preserve_env_vars=""

  printf -v sensor_shell_command 'source %q && exec python %q' \
    "$SENSOR_DIR/.venv/bin/activate" \
    "$SENSOR_DIR/main.py"

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    out_command_ref=(bash -lc "$sensor_shell_command")
    return
  fi

  preserve_env_vars="BACKEND_URL,ZEINAGUARD_NONINTERACTIVE,SENSOR_INTERFACE,ZEINAGUARD_SENSOR_ID,ZEINAGUARD_SENSOR_REGISTRATION_KEY"
  out_command_ref=(sudo --preserve-env="$preserve_env_vars" bash -lc "$sensor_shell_command")
}

verify_sensor_launcher() {
  local sensor_shell_command=""

  printf -v sensor_shell_command 'source %q && command -v python >/dev/null && python -c %q >/dev/null' \
    "$SENSOR_DIR/.venv/bin/activate" \
    'import sys; raise SystemExit(0 if sys.prefix != getattr(sys, "base_prefix", sys.prefix) else 1)'

  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    bash -lc "$sensor_shell_command" || fail "Sensor virtual environment is not usable as root"
    return
  fi

  sudo --preserve-env=BACKEND_URL,ZEINAGUARD_NONINTERACTIVE,SENSOR_INTERFACE,ZEINAGUARD_SENSOR_ID,ZEINAGUARD_SENSOR_REGISTRATION_KEY \
    bash -lc "$sensor_shell_command" || fail "Sensor virtual environment is not usable through sudo"
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

  sleep 1
  process_running "$pid" || fail "$service_name failed to start; see $log_file"
}

wait_for_http_ok() {
  local name="$1"
  local url="$2"
  local timeout_seconds="$3"
  local deadline=$((SECONDS + timeout_seconds))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if python3 - "$url" <<'PY' >/dev/null 2>&1
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        raise SystemExit(0 if 200 <= response.status < 500 else 1)
except Exception:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 2
  done

  tail -n 40 "$LOG_DIR/$name.log" >&2 || true
  return 1
}

wait_for_backend_health() {
  local deadline=$((SECONDS + 60))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if python3 - "$BACKEND_URL/health" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        payload = json.load(response)
except Exception:
    raise SystemExit(1)

raise SystemExit(0 if payload.get("status") == "healthy" else 1)
PY
    then
      return 0
    fi
    sleep 2
  done

  tail -n 60 "$BACKEND_LOG" >&2 || true
  return 1
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

  if [ "$exit_code" -eq 0 ]; then
    log "All services stopped cleanly"
  fi
}

on_interrupt() {
  printf '\n'
  log "Interrupt received, shutting down services"
  cleanup_all 0
  exit 0
}

on_exit() {
  local exit_code="$?"
  if [ "$exit_code" -ne 0 ]; then
    warn "Startup supervisor exited unexpectedly; cleaning up"
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
  while true; do
    local service_name
    local pid

    for service_name in "${START_ORDER[@]}"; do
      pid="${SERVICE_PIDS[$service_name]:-}"
      if ! process_running "$pid"; then
        tail -n 40 "$LOG_DIR/$service_name.log" >&2 || true
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
  ensure_command python3
  ensure_command setsid
  load_env_file
  ensure_runtime_dirs

  ensure_frontend_dependencies
  ensure_python_venv "backend" "$BACKEND_DIR" "$BACKEND_DIR/requirements.txt"
  ensure_python_venv "sensor" "$SENSOR_DIR" "$SENSOR_DIR/requirements.txt"

  ensure_port_available "frontend" "$FRONTEND_PORT"
  ensure_port_available "backend" "$BACKEND_PORT"
  stop_pid_file_if_present "sensor"

  require_sudo_access
  verify_sensor_launcher
  build_sensor_command sensor_command

  start_service "backend" "$BACKEND_DIR" "$BACKEND_LOG" \
    env FLASK_PORT="$BACKEND_PORT" BACKEND_URL="$BACKEND_URL" \
    "$BACKEND_DIR/.venv/bin/python" "$BACKEND_DIR/app.py"
  wait_for_backend_health || fail "Backend failed health check on port ${BACKEND_PORT}"

  start_service "frontend" "$FRONTEND_DIR" "$FRONTEND_LOG" \
    env NEXT_PUBLIC_API_URL="$BACKEND_URL" NEXT_PUBLIC_SOCKET_URL="$BACKEND_URL" \
    pnpm dev
  wait_for_http_ok "frontend" "http://127.0.0.1:${FRONTEND_PORT}" 90 || fail "Frontend did not become reachable on port ${FRONTEND_PORT}"

  start_service "sensor" "$SENSOR_DIR" "$SENSOR_LOG" \
    env BACKEND_URL="$BACKEND_URL" \
    "${sensor_command[@]}"

  print_summary
  monitor_services
}

main "$@"
