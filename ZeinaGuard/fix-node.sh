#!/usr/bin/env bash
set -euo pipefail

NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
NVM_INSTALL_VERSION="${NVM_INSTALL_VERSION:-v0.39.7}"
REQUIRED_NODE_MAJOR="${REQUIRED_NODE_MAJOR:-20}"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

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

fix_node_requested_version() {
  local nvmrc_path="$PROJECT_ROOT/.nvmrc"

  if [ -n "${ZEINAGUARD_NODE_VERSION:-}" ]; then
    printf '%s\n' "$ZEINAGUARD_NODE_VERSION"
    return
  fi

  if [ -f "$nvmrc_path" ]; then
    tr -d '[:space:]' < "$nvmrc_path"
    return
  fi

  printf '%s\n' "$REQUIRED_NODE_MAJOR"
}

fix_node_resolve_install_version() {
  local requested_version="$1"
  local remote_version=""

  remote_version="$(nvm version-remote "$requested_version" 2>/dev/null || true)"
  if [ -n "$remote_version" ] && [ "$remote_version" != "N/A" ]; then
    printf '%s\n' "$remote_version"
    return
  fi

  if [[ "$requested_version" =~ ^[0-9]+$ ]]; then
    remote_version="$(
      nvm ls-remote 2>/dev/null \
        | awk -v major="$requested_version" '$1 ~ "^v" major "\\." { version=$1 } END { if (version) print version }'
    )"
    if [ -n "$remote_version" ]; then
      printf '%s\n' "$remote_version"
      return
    fi
  fi

  fix_node_fail "Unable to resolve Node.js version '$requested_version' from nvm. Try checking internet access to nodejs.org or your nvm mirror settings."
}

fix_node_ensure_node20() {
  local major_version
  local requested_version
  local install_version

  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    fix_node_install_nvm
  fi

  fix_node_log "Loading nvm from $NVM_DIR"
  fix_node_load_nvm
  major_version="$(fix_node_current_major)"
  requested_version="$(fix_node_requested_version)"
  install_version="$(fix_node_resolve_install_version "$requested_version")"

  if [ "$major_version" -lt "$REQUIRED_NODE_MAJOR" ]; then
    fix_node_log "Current Node.js is too old (found major=$major_version). Installing Node.js $install_version."
  else
    fix_node_log "Ensuring Node.js $install_version is active through nvm."
  fi

  nvm install "$install_version" --latest-npm
  fix_node_log "Setting Node.js $install_version as default"
  nvm alias default "$install_version"
  fix_node_log "Activating Node.js $install_version"
  nvm use "$install_version"
  hash -r
}

fix_node_ensure_npm_and_pnpm() {
  fix_node_log "Cleaning npm cache"
  npm cache clean --force >/dev/null 2>&1 || true
  fix_node_log "Updating npm"
  if ! npm install -g npm@latest >/dev/null 2>&1; then
    fix_node_warn "Failed to upgrade npm to the latest version; continuing with the bundled npm."
  fi
  fix_node_log "Installing pnpm globally"
  npm install -g pnpm
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
