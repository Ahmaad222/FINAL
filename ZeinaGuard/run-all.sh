#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"
STATE_DIR="$ROOT_DIR/.zeinaguard-runtime"
ENV_FILE="$ROOT_DIR/.env"
UPDATE_MODE=0

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
      --update)
        UPDATE_MODE=1
        ;;
      *)
        fail "Unknown option: $1"
        ;;
    esac
    shift
  done
}

ensure_runtime_dirs() {
  mkdir -p "$LOG_DIR" "$STATE_DIR"
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

resolve_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi

  fail "Python is required but was not found."
}

PYTHON_BIN="$(resolve_python)"

hash_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
    return
  fi

  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
    return
  fi

  "$PYTHON_BIN" - "$1" <<'PY'
from pathlib import Path
import hashlib
import sys

path = Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

venv_python_path() {
  local venv_dir="$1"
  if [ -x "$venv_dir/bin/python" ]; then
    printf '%s\n' "$venv_dir/bin/python"
    return
  fi

  if [ -x "$venv_dir/Scripts/python.exe" ]; then
    printf '%s\n' "$venv_dir/Scripts/python.exe"
    return
  fi

  printf '%s\n' "$venv_dir/bin/python"
}

ensure_venv() {
  local venv_dir="$1"

  if [ ! -d "$venv_dir" ]; then
    log_step "Creating virtual environment: $venv_dir"
    "$PYTHON_BIN" -m venv "$venv_dir"
  else
    log_skip "Reusing virtual environment: $venv_dir"
  fi
}

ensure_nvm_loaded() {
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    # shellcheck source=/dev/null
    . "$NVM_DIR/nvm.sh"
    return
  fi

  if ! command -v curl >/dev/null 2>&1; then
    fail "curl is required to install nvm automatically."
  fi

  log_step "Installing nvm..."
  curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
  # shellcheck source=/dev/null
  . "$NVM_DIR/nvm.sh"
}

ensure_node_toolchain() {
  local requested_node="20"

  if [ -f "$ROOT_DIR/.nvmrc" ]; then
    requested_node="$(tr -d '[:space:]' < "$ROOT_DIR/.nvmrc")"
  fi

  if ! command -v node >/dev/null 2>&1; then
    ensure_nvm_loaded
    log_step "Installing Node.js $requested_node via nvm..."
    nvm install "$requested_node"
  else
    ensure_nvm_loaded
    nvm install "$requested_node" >/dev/null 2>&1 || true
  fi

  nvm use "$requested_node" >/dev/null
  hash -r

  if command -v corepack >/dev/null 2>&1; then
    corepack enable >/dev/null 2>&1 || true
    corepack prepare pnpm@latest --activate >/dev/null 2>&1 || true
  fi

  command -v node >/dev/null 2>&1 || fail "Node.js setup failed."
  command -v pnpm >/dev/null 2>&1 || fail "pnpm is required but was not found."
}

install_frontend_dependencies() {
  local lock_file="$ROOT_DIR/pnpm-lock.yaml"
  local marker_file="$ROOT_DIR/node_modules/.lock-hash"
  local desired_hash=""
  local current_hash=""

  if [ -f "$lock_file" ]; then
    desired_hash="$(hash_file "$lock_file")"
  fi

  if [ -f "$marker_file" ]; then
    current_hash="$(tr -d '[:space:]' < "$marker_file")"
  fi

  if [ "$UPDATE_MODE" -eq 1 ]; then
    log_step "Updating frontend dependencies..."
    (cd "$ROOT_DIR" && pnpm install)
  elif [ ! -d "$ROOT_DIR/node_modules" ]; then
    log_step "Installing frontend dependencies..."
    (cd "$ROOT_DIR" && pnpm install)
  elif [ -n "$desired_hash" ] && [ "$desired_hash" != "$current_hash" ]; then
    log_step "Lockfile changed. Syncing frontend dependencies..."
    (cd "$ROOT_DIR" && pnpm install)
  else
    log_skip "Frontend dependencies already available"
  fi

  mkdir -p "$ROOT_DIR/node_modules"
  if [ -n "$desired_hash" ]; then
    printf '%s\n' "$desired_hash" > "$marker_file"
  fi
}

install_python_dependencies() {
  local service_name="$1"
  local venv_dir="$2"
  local requirements_file="$3"
  local marker_file="$venv_dir/.requirements-hash"
  local venv_python
  local desired_hash=""
  local current_hash=""

  ensure_venv "$venv_dir"
  venv_python="$(venv_python_path "$venv_dir")"

  if [ ! -f "$requirements_file" ]; then
    fail "Missing requirements file: $requirements_file"
  fi

  desired_hash="$(hash_file "$requirements_file")"
  if [ -f "$marker_file" ]; then
    current_hash="$(tr -d '[:space:]' < "$marker_file")"
  fi

  if [ "$UPDATE_MODE" -eq 1 ]; then
    log_step "Updating $service_name dependencies..."
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -r "$requirements_file"
  elif [ ! -f "$marker_file" ]; then
    log_step "Installing $service_name dependencies..."
    "$venv_python" -m pip install --upgrade pip
    "$venv_python" -m pip install -r "$requirements_file"
  elif [ "$desired_hash" != "$current_hash" ]; then
    log_step "$service_name requirements changed. Syncing dependencies..."
    "$venv_python" -m pip install -r "$requirements_file"
  else
    log_skip "$service_name dependencies already available"
  fi

  printf '%s\n' "$desired_hash" > "$marker_file"
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
  local port="$1"

  "$PYTHON_BIN" - "$port" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.5)

try:
    sock.connect(("127.0.0.1", port))
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
  if port_is_open "$port"; then
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
    tail -n 50 "$log_file" >&2 || true
    fail "$service_name failed to stay running. See $log_file"
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local timeout_seconds="$3"
  local expected_fragment="${4:-}"
  local deadline=$((SECONDS + timeout_seconds))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if "$PYTHON_BIN" - "$url" "$expected_fragment" <<'PY'
from urllib.request import urlopen
import sys

url = sys.argv[1]
expected = sys.argv[2]

try:
    with urlopen(url, timeout=3) as response:
        body = response.read().decode("utf-8", errors="ignore")
except Exception:
    raise SystemExit(1)

if expected and expected not in body:
    raise SystemExit(1)
PY
    then
      return 0
    fi
    sleep 2
  done

  tail -n 60 "$LOG_DIR/$name.log" >&2 || true
  fail "$name health check failed for $url"
}

start_backend() {
  local backend_python

  backend_python="$(venv_python_path "$ROOT_DIR/backend/.venv")"
  log_step "Starting backend"
  ensure_port_available "backend" "5000"
  start_command \
    "backend" \
    "$ROOT_DIR/backend" \
    "$backend_python" \
    app.py
  wait_for_http "backend" "http://localhost:5000/health" 90 '"status": "healthy"'
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
  local sensor_python

  sensor_python="$(venv_python_path "$ROOT_DIR/sensor/.venv")"
  log_step "Starting sensor"
  stop_pid_file "sensor"

  if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
    if sudo -n true >/dev/null 2>&1; then
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
      warn "sudo requires a password. Starting sensor without elevation."
      start_command \
        "sensor" \
        "$ROOT_DIR/sensor" \
        env \
        "BACKEND_URL=${BACKEND_URL:-http://localhost:5000}" \
        "$sensor_python" \
        "$ROOT_DIR/sensor/main.py"
    fi
  else
    start_command \
      "sensor" \
      "$ROOT_DIR/sensor" \
      env \
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
  ensure_runtime_dirs
  ensure_default_env
  load_env
  ensure_node_toolchain
  install_frontend_dependencies
  install_python_dependencies "backend" "$ROOT_DIR/backend/.venv" "$ROOT_DIR/requirements.txt"
  install_python_dependencies "sensor" "$ROOT_DIR/sensor/.venv" "$ROOT_DIR/sensor/requirements.txt"
  start_backend
  start_frontend
  start_sensor
  print_ready
}

main "$@"
