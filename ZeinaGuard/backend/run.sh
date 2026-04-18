#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT_ENV_FILE="$ROOT_DIR/.env"

if [ -f "$ROOT_ENV_FILE" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT_ENV_FILE"
  set +a
fi

bash "$ROOT_DIR/fix-python.sh" backend

cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/.venv/bin/gunicorn" --worker-class eventlet --bind 0.0.0.0:5000 app:app
