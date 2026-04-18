#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck source=/dev/null
source "$ROOT_DIR/fix-node.sh"
echo "[frontend] Ensuring Node.js 20, npm, and pnpm..."
ensure_zeinaguard_node_toolchain

needs_chown=0
if [ ! -w "$ROOT_DIR" ]; then
  needs_chown=1
elif [ -d "$ROOT_DIR/node_modules" ] && [ ! -w "$ROOT_DIR/node_modules" ]; then
  needs_chown=1
fi

if [ -n "${USER:-}" ] && [ "$needs_chown" -eq 1 ] && command -v sudo >/dev/null 2>&1; then
  echo "[frontend] Fixing ownership..."
  sudo chown -R "$USER:$USER" "$ROOT_DIR" || true
else
  echo "[frontend] Ownership looks okay."
fi

cd "$ROOT_DIR"
echo "[frontend] Cleaning npm cache..."
npm cache clean --force >/dev/null 2>&1 || true
echo "[frontend] Removing node_modules and package-lock.json..."
rm -rf node_modules
rm -f package-lock.json
echo "[frontend] Installing dependencies with pnpm..."
pnpm install
echo "[frontend] Starting dev server..."
exec pnpm dev
