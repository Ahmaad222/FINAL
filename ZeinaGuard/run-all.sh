#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
LOG_DIR="$ROOT_DIR/logs"
STATE_DIR="$ROOT_DIR/.zeinaguard-runtime"

log() {
  printf '[run-all] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

run_maybe_sudo() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    fail "This action requires sudo: $*"
  fi
}

ensure_linux() {
  [ "$(uname -s)" = "Linux" ] || fail "ZeinaGuard local launcher supports Linux only."
}

ensure_default_env() {
  if [ -f "$ENV_FILE" ]; then
    return
  fi

  cat >"$ENV_FILE" <<'EOF'
POSTGRES_USER=zeinaguard_user
POSTGRES_PASSWORD=secure_password
POSTGRES_DB=zeinaguard_db
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

BACKEND_URL=http://localhost:5000
NEXT_PUBLIC_SOCKET_URL=http://localhost:5000
NEXT_PUBLIC_API_URL=http://localhost:5000

JWT_SECRET_KEY=super_secret_key
EOF
  log "Created default .env file at $ENV_FILE"
}

load_env() {
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
}

ensure_runtime_dirs() {
  mkdir -p "$LOG_DIR" "$STATE_DIR"
}

fix_project_permissions() {
  if [ -n "${USER:-}" ]; then
    run_maybe_sudo chown -R "$USER:$USER" "$ROOT_DIR" || true
  fi
}

pid_file_for() {
  printf '%s/%s.pid\n' "$STATE_DIR" "$1"
}

process_running() {
  local pid="$1"
  kill -0 "$pid" >/dev/null 2>&1
}

wait_for_process_exit() {
  local pid="$1"
  local attempts=0

  while process_running "$pid" && [ "$attempts" -lt 50 ]; do
    sleep 0.2
    attempts=$((attempts + 1))
  done

  if process_running "$pid"; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
}

stop_pid_file() {
  local name="$1"
  local pid_file
  local pid

  pid_file="$(pid_file_for "$name")"
  if [ ! -f "$pid_file" ]; then
    return
  fi

  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && process_running "$pid"; then
    log "Stopping previous $name process ($pid)"
    kill "$pid" >/dev/null 2>&1 || true
    wait_for_process_exit "$pid"
  fi

  rm -f "$pid_file"
}

port_is_open() {
  local host="$1"
  local port="$2"

  python3 - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])

sock = socket.socket()
sock.settimeout(1)

try:
    sock.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

ensure_port_available() {
  local service_name="$1"
  local port="$2"

  stop_pid_file "$service_name"
  if port_is_open "127.0.0.1" "$port"; then
    fail "Port $port is already in use. Free it before starting $service_name."
  fi
}

start_command() {
  local service_name="$1"
  local workdir="$2"
  shift 2

  local log_file="$LOG_DIR/$service_name.log"
  local pid_file
  local pid

  pid_file="$(pid_file_for "$service_name")"
  : >"$log_file"

  (
    cd "$workdir"
    nohup "$@" >>"$log_file" 2>&1 &
    echo $! >"$pid_file"
  )

  sleep 1
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -z "$pid" ] || ! process_running "$pid"; then
    tail -n 40 "$log_file" >&2 || true
    fail "$service_name failed to stay running. See $log_file"
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local timeout_seconds="$3"
  local expected_fragment="${4:-}"
  local deadline=$((SECONDS + timeout_seconds))
  local response=""

  while [ "$SECONDS" -lt "$deadline" ]; do
    response="$(curl -fsS --max-time 3 "$url" 2>/dev/null || true)"
    if [ -n "$response" ]; then
      if [ -z "$expected_fragment" ] || printf '%s' "$response" | grep -qi "$expected_fragment"; then
        return 0
      fi
    fi
    sleep 2
  done

  tail -n 60 "$LOG_DIR/$name.log" >&2 || true
  fail "$name health check failed for $url"
}

prepare_frontend() {
  log "Preparing frontend toolchain"
  # shellcheck source=/dev/null
  source "$ROOT_DIR/fix-node.sh"
  ensure_zeinaguard_node_toolchain

  fix_project_permissions
  npm cache clean --force >/dev/null 2>&1 || true

  rm -rf "$ROOT_DIR/node_modules"
  rm -f "$ROOT_DIR/package-lock.json"

  log "Installing frontend dependencies with pnpm"
  (
    cd "$ROOT_DIR"
    pnpm install
  )
}

prepare_python_envs() {
  log "Rebuilding backend virtual environment"
  bash "$ROOT_DIR/fix-python.sh" backend

  log "Rebuilding sensor virtual environment"
  bash "$ROOT_DIR/fix-python.sh" sensor
}

start_backend() {
  log "Starting backend"
  ensure_port_available "backend" "5000"
  start_command \
    "backend" \
    "$ROOT_DIR/backend" \
    "$ROOT_DIR/backend/.venv/bin/gunicorn" \
    --worker-class eventlet \
    --bind 0.0.0.0:5000 \
    app:app
  wait_for_http "backend" "http://localhost:5000/health" 90 '"status":"healthy"'
}

start_frontend() {
  log "Starting frontend"
  ensure_port_available "frontend" "3000"
  start_command \
    "frontend" \
    "$ROOT_DIR" \
    pnpm \
    dev
  wait_for_http "frontend" "http://localhost:3000" 120
}

start_sensor() {
  local sensor_python="$ROOT_DIR/sensor/.venv/bin/python"
  log "Starting sensor"
  stop_pid_file "sensor"

  if command -v sudo >/dev/null 2>&1; then
    sudo -v
    start_command \
      "sensor" \
      "$ROOT_DIR/sensor" \
      sudo \
      -E \
      env \
      "BACKEND_URL=${BACKEND_URL:-http://localhost:5000}" \
      "$sensor_python" \
      "$ROOT_DIR/sensor/main.py"
  else
    warn "sudo is unavailable. Starting sensor without elevated privileges."
    start_command \
      "sensor" \
      "$ROOT_DIR/sensor" \
      env \
      "BACKEND_URL=${BACKEND_URL:-http://localhost:5000}" \
      "$sensor_python" \
      "$ROOT_DIR/sensor/main.py"
  fi
}

print_ready() {
  cat <<EOF
READY
Frontend: http://localhost:3000
Backend : http://localhost:5000
Logs:
  $LOG_DIR/backend.log
  $LOG_DIR/frontend.log
  $LOG_DIR/sensor.log
EOF
}

main() {
  ensure_linux
  ensure_default_env
  load_env
  ensure_runtime_dirs

  bash "$ROOT_DIR/setup-check.sh"
  load_env

  prepare_frontend
  prepare_python_envs
  start_backend
  start_frontend
  start_sensor
  print_ready
}

main "$@"
