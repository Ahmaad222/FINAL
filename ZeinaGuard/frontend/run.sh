#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=/dev/null
source "$ROOT_DIR/fix-node.sh"
ensure_zeinaguard_node_toolchain

if [ -n "${USER:-}" ] && command -v sudo >/dev/null 2>&1; then
  sudo chown -R "$USER:$USER" "$ROOT_DIR" || true
fi

cd "$ROOT_DIR"
npm cache clean --force >/dev/null 2>&1 || true
rm -rf node_modules
rm -f package-lock.json
pnpm install
exec pnpm dev
