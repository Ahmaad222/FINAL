#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

resolve_package_manager() {
  if command -v pnpm >/dev/null 2>&1; then
    PACKAGE_MANAGER="pnpm"
    return 0
  fi

  if command -v npm >/dev/null 2>&1; then
    PACKAGE_MANAGER="npm"
    return 0
  fi

  if command -v corepack >/dev/null 2>&1 && corepack pnpm --version >/dev/null 2>&1; then
    PACKAGE_MANAGER="corepack-pnpm"
    return 0
  fi

  echo "Neither pnpm nor npm is installed. Please install Node.js + npm, or pnpm." >&2
  exit 1
}

frontend_dependencies_ready() {
  [ -x "$ROOT_DIR/node_modules/.bin/next" ]
}

install_dependencies() {
  case "$PACKAGE_MANAGER" in
    pnpm)
      pnpm install
      ;;
    npm)
      npm install
      ;;
    corepack-pnpm)
      corepack pnpm install
      ;;
  esac
}

start_dev_server() {
  case "$PACKAGE_MANAGER" in
    pnpm)
      exec pnpm dev
      ;;
    npm)
      exec npm run dev
      ;;
    corepack-pnpm)
      exec corepack pnpm dev
      ;;
  esac
}

resolve_package_manager

if frontend_dependencies_ready; then
  echo "Frontend dependencies already present. Skipping install."
else
  echo "Installing frontend dependencies with $PACKAGE_MANAGER..."
  install_dependencies
fi

echo "Starting frontend with $PACKAGE_MANAGER..."
start_dev_server
