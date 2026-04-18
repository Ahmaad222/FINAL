#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_NAME="${1:-sensor}"
TARGET_DIR="$ROOT_DIR/$TARGET_NAME"
REQUIREMENTS_FILE="${2:-$TARGET_DIR/requirements.txt}"
VENV_DIR="$TARGET_DIR/.venv"

log() {
  printf '[fix-python] %s\n' "$*"
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
  [ "$(uname -s)" = "Linux" ] || fail "fix-python.sh supports Linux only."
}

ensure_python_packages() {
  if ! command -v apt-get >/dev/null 2>&1; then
    fail "Automatic Python dependency installation currently supports apt-get based Linux distributions."
  fi

  log "Ensuring python3, python3-venv, and python3-pip are installed"
  run_maybe_sudo apt-get update
  run_maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv
}

validate_target() {
  [ -d "$TARGET_DIR" ] || fail "Target directory not found: $TARGET_DIR"
  [ -f "$REQUIREMENTS_FILE" ] || fail "Requirements file not found: $REQUIREMENTS_FILE"
}

fix_permissions() {
  if [ -n "${USER:-}" ]; then
    run_maybe_sudo chown -R "$USER:$USER" "$TARGET_DIR" || true
  fi
}

recreate_virtualenv() {
  log "Recreating virtual environment in $VENV_DIR"
  rm -rf "$VENV_DIR"
  python3 -m venv "$VENV_DIR"
}

install_python_deps() {
  log "Bootstrapping pip"
  "$VENV_DIR/bin/python" -m ensurepip --upgrade
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

  log "Installing requirements from $REQUIREMENTS_FILE"
  "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS_FILE"
  "$VENV_DIR/bin/python" -m pip install psutil
}

verify_python_deps() {
  "$VENV_DIR/bin/python" - <<'PY'
import pip  # noqa: F401
import psutil  # noqa: F401
PY
}

main() {
  ensure_linux
  validate_target
  ensure_python_packages
  fix_permissions
  recreate_virtualenv
  install_python_deps
  verify_python_deps
  log "Python environment ready for $TARGET_NAME"
}

main "$@"
