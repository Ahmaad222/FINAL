#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
ROOT_ENV_FILE="$SCRIPT_DIR/../.env"

cd "$SCRIPT_DIR"

if [ -f "$ROOT_ENV_FILE" ]; then
  set -a
  source "$ROOT_ENV_FILE"
  set +a
fi

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install -r requirements.txt

exec gunicorn --worker-class eventlet --bind 0.0.0.0:5000 app:app
