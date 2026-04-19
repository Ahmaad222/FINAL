#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
LOG_DIR="$ROOT_DIR/logs"
STATE_DIR="$ROOT_DIR/.zeinaguard-runtime"
FAST_MODE=0

log_step() {
  printf '[run-all] %s\n' "$*"
}

log_ok() {
  printf '[OK] %s\n' "$*"
}

log_skip() {
  printf '[SKIP] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --fast)
        FAST_MODE=1
        ;;
      *)
        fail "Unknown option: $1"
        ;;
    esac
    shift
  done
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
  log_ok "Created default .env file"
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
  if [ -z "${USER:-}" ]; then
    return
  fi

  if [ -w "$ROOT_DIR" ] && { [ ! -d "$ROOT_DIR/node_modules" ] || [ -w "$ROOT_DIR/node_modules" ]; }; then
    return
  fi

  log_step "Fixing project ownership"
  run_maybe_sudo chown -R "$USER:$USER" "$ROOT_DIR" || true
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
    log_step "Stopping previous $name process ($pid)"
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

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

prepare_frontend() {
  local lock_file="$ROOT_DIR/pnpm-lock.yaml"
  local lock_hash_file="$ROOT_DIR/node_modules/.pnpm-lock.sha256"
  local current_lock_hash=""
  local saved_lock_hash=""

  log_step "Preparing frontend toolchain"
  # shellcheck source=/dev/null
  source "$ROOT_DIR/fix-node.sh"

  if [ "$FAST_MODE" = "1" ]; then
    if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
      fix_node_load_nvm
      nvm use "$(fix_node_requested_version)" >/dev/null 2>&1 || true
      hash -r
    fi
    command -v pnpm >/dev/null 2>&1 || fail "Fast mode requires pnpm to already be installed."
    [ -d "$ROOT_DIR/node_modules" ] || fail "Fast mode requires existing node_modules."
    log_skip "Frontend dependency install skipped (--fast)"
    return
  fi

  ensure_zeinaguard_node_toolchain

  fix_project_permissions

  if [ -f "$lock_file" ]; then
    current_lock_hash="$(sha256_file "$lock_file")"
  fi
  if [ -f "$lock_hash_file" ]; then
    saved_lock_hash="$(tr -d '[:space:]' < "$lock_hash_file")"
  fi

  if [ -d "$ROOT_DIR/node_modules" ] && [ -n "$current_lock_hash" ] && [ "$current_lock_hash" = "$saved_lock_hash" ]; then
    log_skip "Frontend dependencies already installed"
    return
  fi

  log_step "Installing frontend dependencies with pnpm"
  (
    cd "$ROOT_DIR"
    pnpm install
  )
  mkdir -p "$ROOT_DIR/node_modules"
  if [ -n "$current_lock_hash" ]; then
    printf '%s\n' "$current_lock_hash" > "$lock_hash_file"
  fi
  log_ok "Frontend dependencies ready"
}

prepare_python_envs() {
  if [ "$FAST_MODE" = "1" ]; then
    ZEINAGUARD_FAST=1 bash "$ROOT_DIR/fix-python.sh" backend --fast
    ZEINAGUARD_FAST=1 bash "$ROOT_DIR/fix-python.sh" sensor --fast
    return
  fi

  bash "$ROOT_DIR/fix-python.sh" backend
  bash "$ROOT_DIR/fix-python.sh" sensor
}

start_backend() {
  log_step "Starting backend"
  ensure_port_available "backend" "5000"
  start_command \
    "backend" \
    "$ROOT_DIR/backend" \
    "$ROOT_DIR/backend/.venv/bin/gunicorn" \
    --worker-class eventlet \
    --bind 0.0.0.0:5000 \
    app:app
  wait_for_http "backend" "http://localhost:5000/health" 90 '"status":"healthy"'
  log_ok "Backend ready"
}

start_frontend() {
  log_step "Starting frontend"
  ensure_port_available "frontend" "3000"
  start_command \
    "frontend" \
    "$ROOT_DIR" \
    pnpm \
    dev
  wait_for_http "frontend" "http://localhost:3000" 120
  log_ok "Frontend ready"
}

start_sensor() {
  local sensor_python="$ROOT_DIR/sensor/.venv/bin/python"

  log_step "Starting sensor"
  stop_pid_file "sensor"

  if command -v sudo >/dev/null 2>&1; then
    sudo -v
    start_command \
      "sensor" \
      "$ROOT_DIR/sensor" \
      sudo \
      -E \
      env \
      "ZEINAGUARD_NONINTERACTIVE=1" \
      "BACKEND_URL=${BACKEND_URL:-http://localhost:5000}" \
      "$sensor_python" \
      "$ROOT_DIR/sensor/main.py"
  else
    warn "sudo is unavailable. Starting sensor without elevated privileges."
    start_command \
      "sensor" \
      "$ROOT_DIR/sensor" \
      env \
      "ZEINAGUARD_NONINTERACTIVE=1" \
      "BACKEND_URL=${BACKEND_URL:-http://localhost:5000}" \
      "$sensor_python" \
      "$ROOT_DIR/sensor/main.py"
  fi

  log_ok "Sensor running"
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
  parse_args "$@"
  ensure_linux
  ensure_default_env
  load_env
  ensure_runtime_dirs

  if [ "$FAST_MODE" = "1" ]; then
    log_skip "Skipping setup checks (--fast)"
  else
    bash "$ROOT_DIR/setup-check.sh"
    load_env
  fi

  prepare_frontend
  prepare_python_envs
  start_backend
  start_frontend
  start_sensor
  print_ready
}

main "$@"
