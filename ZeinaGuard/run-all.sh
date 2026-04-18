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

echo "Starting ZeinaGuard locally..."

echo "Ensuring PostgreSQL and Redis are running..."
sudo service postgresql start || true
sudo service redis-server start || true

echo "Starting backend..."
run_in_terminal "ZeinaGuard Backend" "cd '$ROOT_DIR/backend' && bash ./run.sh"

echo "Starting frontend..."
run_in_terminal "ZeinaGuard Frontend" "cd '$ROOT_DIR/frontend' && bash ./run.sh"

echo "Starting sensor..."
run_in_terminal "ZeinaGuard Sensor" "cd '$ROOT_DIR/sensor' && sudo -E env BACKEND_URL='${BACKEND_URL:-http://localhost:5000}' python3 main.py"

echo "All services started."
echo "Frontend: http://localhost:3000"
echo "Backend : http://localhost:5000"
