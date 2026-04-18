#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

run_in_terminal() {
  local title="$1"
  local command="$2"

  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash -lc "$command; exec bash"
  else
    bash -lc "$command" &
  fi
}

warn() {
  echo "[warn] $*" >&2
}

run_maybe_sudo() {
  if command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    "$@"
  fi
}

port_ready() {
  local host="$1"
  local port="$2"

  if ! command -v python3 >/dev/null 2>&1; then
    return 1
  fi

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

postgres_ready() {
  if command -v pg_isready >/dev/null 2>&1; then
    pg_isready -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" >/dev/null 2>&1
    return 0
  fi

  port_ready "${POSTGRES_HOST:-localhost}" "${POSTGRES_PORT:-5432}"
}

redis_ready() {
  if command -v redis-cli >/dev/null 2>&1; then
    if [ -n "${REDIS_PASSWORD:-}" ]; then
      redis-cli -a "${REDIS_PASSWORD}" -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1 && return 0
    else
      redis-cli -h "${REDIS_HOST:-localhost}" -p "${REDIS_PORT:-6379}" ping >/dev/null 2>&1 && return 0
    fi
  fi

  port_ready "${REDIS_HOST:-localhost}" "${REDIS_PORT:-6379}"
}

start_service_if_available() {
  local service_name="$1"

  if command -v service >/dev/null 2>&1; then
    run_maybe_sudo service "$service_name" start
    return $?
  fi

  if command -v systemctl >/dev/null 2>&1; then
    run_maybe_sudo systemctl start "$service_name"
    return $?
  fi

  return 1
}

ensure_postgresql() {
  if postgres_ready; then
    return 0
  fi

  start_service_if_available postgresql >/dev/null 2>&1 || true

  if postgres_ready; then
    return 0
  fi

  warn "PostgreSQL is required but was not reachable on ${POSTGRES_HOST:-localhost}:${POSTGRES_PORT:-5432}."
  warn "Install/start PostgreSQL, create the '${POSTGRES_DB:-zeinaguard_db}' database, then rerun ./run-all.sh."
  return 1
}

ensure_redis() {
  if redis_ready; then
    return 0
  fi

  start_service_if_available redis-server >/dev/null 2>&1 || true

  if redis_ready; then
    return 0
  fi

  start_service_if_available redis >/dev/null 2>&1 || true

  if redis_ready; then
    return 0
  fi

  if command -v redis-server >/dev/null 2>&1; then
    redis-server --daemonize yes >/dev/null 2>&1 || true
  fi

  if redis_ready; then
    return 0
  fi

  warn "Redis was not detected. The app may still run, but realtime features can be degraded until Redis is installed/running."
  return 0
}

echo "Starting ZeinaGuard locally..."

echo "Ensuring PostgreSQL and Redis are running..."
ensure_postgresql
ensure_redis

echo "Starting backend..."
run_in_terminal "ZeinaGuard Backend" "cd '$ROOT_DIR/backend' && bash ./run.sh"

echo "Starting frontend..."
run_in_terminal "ZeinaGuard Frontend" "cd '$ROOT_DIR/frontend' && bash ./run.sh"

echo "Starting sensor..."
if command -v sudo >/dev/null 2>&1; then
  SENSOR_COMMAND="cd '$ROOT_DIR/sensor' && sudo -E env BACKEND_URL='${BACKEND_URL:-http://localhost:5000}' python3 main.py"
else
  SENSOR_COMMAND="cd '$ROOT_DIR/sensor' && env BACKEND_URL='${BACKEND_URL:-http://localhost:5000}' python3 main.py"
fi
run_in_terminal "ZeinaGuard Sensor" "$SENSOR_COMMAND"

echo "Startup commands launched."
echo "Frontend: http://localhost:3000"
echo "Backend : http://localhost:5000"
