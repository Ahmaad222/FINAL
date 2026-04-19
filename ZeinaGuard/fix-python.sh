#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_NAME="${1:-sensor}"
TARGET_DIR="$ROOT_DIR/$TARGET_NAME"
REQUIREMENTS_FILE="$TARGET_DIR/requirements.txt"
VENV_DIR="$TARGET_DIR/.venv"
REQ_HASH_FILE="$VENV_DIR/.req_hash"
FAST_MODE="${ZEINAGUARD_FAST:-0}"

if [ -n "${2:-}" ] && [ "${2:-}" != "--fast" ]; then
  REQUIREMENTS_FILE="$2"
fi

if [ "${3:-}" = "--fast" ] || [ "${2:-}" = "--fast" ]; then
  FAST_MODE=1
fi

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

validate_target() {
  [ -d "$TARGET_DIR" ] || fail "Target directory not found: $TARGET_DIR"
  [ -f "$REQUIREMENTS_FILE" ] || fail "Requirements file not found: $REQUIREMENTS_FILE"
}

ensure_python_packages() {
  local missing=0

  command -v python3 >/dev/null 2>&1 || missing=1
  python3 -m venv --help >/dev/null 2>&1 || missing=1
  python3 -m pip --version >/dev/null 2>&1 || missing=1

  if [ "$missing" -eq 0 ]; then
    return
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    fail "Automatic Python dependency installation currently supports apt-get based Linux distributions."
  fi

  log "Installing python3, python3-venv, and python3-pip"
  run_maybe_sudo apt-get update
  run_maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv
}

fix_permissions() {
  if [ -n "${USER:-}" ]; then
    run_maybe_sudo chown -R "$USER:$USER" "$TARGET_DIR" >/dev/null 2>&1 || true
  fi
}

ensure_virtualenv() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    return
  fi

  log "Creating virtual environment in $VENV_DIR"
  python3 -m venv "$VENV_DIR"
}

requirements_hash() {
  sha256sum "$REQUIREMENTS_FILE" | awk '{print $1}'
}

stored_requirements_hash() {
  if [ -f "$REQ_HASH_FILE" ]; then
    tr -d '[:space:]' < "$REQ_HASH_FILE"
  fi
}

install_python_deps() {
  local current_hash="$1"

  log "Bootstrapping pip for $TARGET_NAME"
  "$VENV_DIR/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel

  log "Installing requirements for $TARGET_NAME"
  "$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS_FILE"
  "$VENV_DIR/bin/python" -m pip install psutil
  printf '%s\n' "$current_hash" > "$REQ_HASH_FILE"
}

verify_virtualenv() {
  "$VENV_DIR/bin/python" - <<'PY'
import pip  # noqa: F401
import psutil  # noqa: F401
PY
}

main() {
  local current_hash=""
  local saved_hash=""

  ensure_linux
  validate_target

  if [ "$FAST_MODE" = "1" ]; then
    [ -x "$VENV_DIR/bin/python" ] || fail "Fast mode requires an existing virtual environment at $VENV_DIR"
    log "[SKIP] Fast mode enabled for $TARGET_NAME"
    exit 0
  fi

  ensure_python_packages
  fix_permissions
  ensure_virtualenv

  current_hash="$(requirements_hash)"
  saved_hash="$(stored_requirements_hash)"

  if [ -x "$VENV_DIR/bin/python" ] && [ "$current_hash" = "$saved_hash" ]; then
    log "[SKIP] Dependencies already installed for $TARGET_NAME"
    verify_virtualenv
    log "[OK] Python environment ready for $TARGET_NAME"
    exit 0
  fi

  install_python_deps "$current_hash"
  verify_virtualenv
  log "[OK] Python environment ready for $TARGET_NAME"
}

main "$@"
