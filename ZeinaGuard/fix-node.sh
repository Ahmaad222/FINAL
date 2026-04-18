#!/usr/bin/env bash
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
NVM_INSTALL_VERSION="${NVM_INSTALL_VERSION:-v0.39.7}"
REQUIRED_NODE_MAJOR="${REQUIRED_NODE_MAJOR:-20}"

log() {
  printf '[fix-node] %s\n' "$*"
}

warn() {
  printf '[WARN] %s\n' "$*" >&2
}

finish() {
  local exit_code="${1:-0}"
  if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return "$exit_code"
  fi
  exit "$exit_code"
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  finish 1
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
  [ "$(uname -s)" = "Linux" ] || fail "fix-node.sh supports Linux only."
}

ensure_curl() {
  if command -v curl >/dev/null 2>&1; then
    return
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    fail "curl is required and automatic installation is only supported on apt-get based systems."
  fi

  run_maybe_sudo apt-get update
  run_maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates
}

install_nvm() {
  log "Installing nvm $NVM_INSTALL_VERSION"
  mkdir -p "$NVM_DIR"
  curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_INSTALL_VERSION/install.sh" | bash
}

load_nvm() {
  [ -s "$NVM_DIR/nvm.sh" ] || fail "nvm installation is incomplete."
  # shellcheck source=/dev/null
  . "$NVM_DIR/nvm.sh"
}

current_node_major() {
  if ! command -v node >/dev/null 2>&1; then
    printf '0\n'
    return
  fi

  node -p "process.versions.node.split('.')[0]" 2>/dev/null || printf '0\n'
}

ensure_node20() {
  local major_version

  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    install_nvm
  fi

  load_nvm
  major_version="$(current_node_major)"

  if [ "$major_version" -lt "$REQUIRED_NODE_MAJOR" ]; then
    log "Current Node.js is too old (found major=$major_version). Installing Node.js $REQUIRED_NODE_MAJOR."
  else
    log "Ensuring Node.js $REQUIRED_NODE_MAJOR is active through nvm."
  fi

  nvm install "$REQUIRED_NODE_MAJOR" --latest-npm >/dev/null
  nvm alias default "$REQUIRED_NODE_MAJOR" >/dev/null
  nvm use "$REQUIRED_NODE_MAJOR" >/dev/null
  hash -r
}

ensure_npm_and_pnpm() {
  npm cache clean --force >/dev/null 2>&1 || true
  if ! npm install -g npm@latest >/dev/null 2>&1; then
    warn "Failed to upgrade npm to the latest version; continuing with the bundled npm."
  fi
  npm install -g pnpm >/dev/null
  hash -r
}

main() {
  ensure_linux
  ensure_curl
  ensure_node20
  ensure_npm_and_pnpm
  log "Using Node.js $(node -v), npm $(npm -v), pnpm $(pnpm -v)"
}

main "$@"
