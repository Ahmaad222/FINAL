#!/usr/bin/env bash
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
NVM_INSTALL_VERSION="${NVM_INSTALL_VERSION:-v0.39.7}"
REQUIRED_NODE_MAJOR="${REQUIRED_NODE_MAJOR:-20}"

fix_node_log() {
  printf '[fix-node] %s\n' "$*"
}

fix_node_warn() {
  printf '[WARN] %s\n' "$*" >&2
}

fix_node_finish() {
  local exit_code="${1:-0}"
  if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return "$exit_code"
  fi
  exit "$exit_code"
}

fix_node_fail() {
  printf '[ERROR] %s\n' "$*" >&2
  fix_node_finish 1
}

fix_node_run_maybe_sudo() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    fix_node_fail "This action requires sudo: $*"
  fi
}

fix_node_ensure_linux() {
  [ "$(uname -s)" = "Linux" ] || fix_node_fail "fix-node.sh supports Linux only."
}

fix_node_ensure_curl() {
  if command -v curl >/dev/null 2>&1; then
    return
  fi

  if ! command -v apt-get >/dev/null 2>&1; then
    fix_node_fail "curl is required and automatic installation is only supported on apt-get based systems."
  fi

  fix_node_run_maybe_sudo apt-get update
  fix_node_run_maybe_sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y curl ca-certificates
}

fix_node_install_nvm() {
  fix_node_log "Installing nvm $NVM_INSTALL_VERSION"
  mkdir -p "$NVM_DIR"
  curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_INSTALL_VERSION/install.sh" | bash
}

fix_node_load_nvm() {
  [ -s "$NVM_DIR/nvm.sh" ] || fix_node_fail "nvm installation is incomplete."
  # shellcheck source=/dev/null
  . "$NVM_DIR/nvm.sh"
}

fix_node_current_major() {
  if ! command -v node >/dev/null 2>&1; then
    printf '0\n'
    return
  fi

  node -p "process.versions.node.split('.')[0]" 2>/dev/null || printf '0\n'
}

fix_node_ensure_node20() {
  local major_version

  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    fix_node_install_nvm
  fi

  fix_node_load_nvm
  major_version="$(fix_node_current_major)"

  if [ "$major_version" -lt "$REQUIRED_NODE_MAJOR" ]; then
    fix_node_log "Current Node.js is too old (found major=$major_version). Installing Node.js $REQUIRED_NODE_MAJOR."
  else
    fix_node_log "Ensuring Node.js $REQUIRED_NODE_MAJOR is active through nvm."
  fi

  nvm install "$REQUIRED_NODE_MAJOR" --latest-npm >/dev/null
  nvm alias default "$REQUIRED_NODE_MAJOR" >/dev/null
  nvm use "$REQUIRED_NODE_MAJOR" >/dev/null
  hash -r
}

fix_node_ensure_npm_and_pnpm() {
  npm cache clean --force >/dev/null 2>&1 || true
  if ! npm install -g npm@latest >/dev/null 2>&1; then
    fix_node_warn "Failed to upgrade npm to the latest version; continuing with the bundled npm."
  fi
  npm install -g pnpm >/dev/null
  hash -r
}

ensure_zeinaguard_node_toolchain() {
  fix_node_ensure_linux
  fix_node_ensure_curl
  fix_node_ensure_node20
  fix_node_ensure_npm_and_pnpm
  fix_node_log "Using Node.js $(node -v), npm $(npm -v), pnpm $(pnpm -v)"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  ensure_zeinaguard_node_toolchain "$@"
fi
