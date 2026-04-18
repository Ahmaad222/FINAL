#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"

log() {
  printf '[setup-check] %s\n' "$*"
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
  [ "$(uname -s)" = "Linux" ] || fail "setup-check.sh supports Linux only."
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
}

load_env() {
  set -a
  # shellcheck source=/dev/null
  source "$ENV_FILE"
  set +a
}

install_required_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    fail "Automatic package installation currently supports apt-get based Linux distributions."
  fi

  log "Installing required system packages"
  run_maybe_sudo apt-get update
  run_maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    libpq-dev \
    lsof \
    postgresql \
    postgresql-client \
    postgresql-contrib \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv
}

install_optional_redis() {
  if command -v redis-server >/dev/null 2>&1 && command -v redis-cli >/dev/null 2>&1; then
    return
  fi

  log "Attempting to install optional Redis"
  if ! run_maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y redis-server; then
    warn "Redis installation failed. Realtime features will run in degraded mode."
  fi
}

start_service_if_available() {
  local service_name="$1"

  if command -v systemctl >/dev/null 2>&1; then
    run_maybe_sudo systemctl start "$service_name" >/dev/null 2>&1 && return 0
  fi

  if command -v service >/dev/null 2>&1; then
    run_maybe_sudo service "$service_name" start >/dev/null 2>&1 && return 0
  fi

  return 1
}

run_postgres_command() {
  run_maybe_sudo -u postgres bash -lc "cd /tmp && $1"
}

sql_escape() {
  printf "%s" "$1" | sed "s/'/''/g"
}

ensure_postgres_ready() {
  log "Ensuring PostgreSQL is running"
  start_service_if_available postgresql || true

  if ! pg_isready -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" >/dev/null 2>&1; then
    fail "PostgreSQL is not reachable on ${POSTGRES_HOST:-localhost}:${POSTGRES_PORT:-5432}"
  fi
}

ensure_postgres_role_and_db() {
  local postgres_user_escaped
  local postgres_password_escaped
  local postgres_db_escaped
  local role_exists
  local db_exists

  postgres_user_escaped="$(sql_escape "${POSTGRES_USER:-zeinaguard_user}")"
  postgres_password_escaped="$(sql_escape "${POSTGRES_PASSWORD:-secure_password}")"
  postgres_db_escaped="$(sql_escape "${POSTGRES_DB:-zeinaguard_db}")"

  log "Ensuring PostgreSQL role and database exist"
  role_exists="$(
    run_postgres_command "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname = '${postgres_user_escaped}'\" postgres" \
      | tr -d '[:space:]'
  )"

  if [ "$role_exists" = "1" ]; then
    run_postgres_command "psql -v ON_ERROR_STOP=1 -d postgres -c \"ALTER ROLE \\\"${POSTGRES_USER:-zeinaguard_user}\\\" WITH LOGIN PASSWORD '${postgres_password_escaped}';\""
  else
    run_postgres_command "psql -v ON_ERROR_STOP=1 -d postgres -c \"CREATE ROLE \\\"${POSTGRES_USER:-zeinaguard_user}\\\" LOGIN PASSWORD '${postgres_password_escaped}';\""
  fi

  db_exists="$(
    run_postgres_command "psql -tAc \"SELECT 1 FROM pg_database WHERE datname = '${postgres_db_escaped}'\" postgres" \
      | tr -d '[:space:]'
  )"

  if [ "$db_exists" != "1" ]; then
    run_postgres_command "createdb -O \"${POSTGRES_USER:-zeinaguard_user}\" \"${POSTGRES_DB:-zeinaguard_db}\""
  fi

  run_postgres_command "psql -v ON_ERROR_STOP=1 -d postgres -c \"GRANT ALL PRIVILEGES ON DATABASE \\\"${POSTGRES_DB:-zeinaguard_db}\\\" TO \\\"${POSTGRES_USER:-zeinaguard_user}\\\";\""
}

ensure_redis_state() {
  if ! command -v redis-cli >/dev/null 2>&1; then
    warn "Redis missing - realtime features degraded"
    return 0
  fi

  if redis-cli ping >/dev/null 2>&1; then
    return 0
  fi

  start_service_if_available redis-server || start_service_if_available redis || true

  if redis-cli ping >/dev/null 2>&1; then
    return 0
  fi

  warn "Redis missing - realtime features degraded"
}

main() {
  ensure_linux
  ensure_default_env
  load_env
  install_required_packages
  install_optional_redis
  ensure_postgres_ready
  ensure_postgres_role_and_db
  ensure_redis_state
}

main "$@"
