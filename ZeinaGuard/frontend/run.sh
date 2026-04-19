#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$ROOT_DIR/pnpm-lock.yaml"
LOCK_HASH_FILE="$ROOT_DIR/node_modules/.pnpm-lock.sha256"
FAST_MODE="${ZEINAGUARD_FAST:-0}"

sha256_file() {
  sha256sum "$1" | awk '{print $1}'
}

# shellcheck source=/dev/null
source "$ROOT_DIR/fix-node.sh"

if [ "$FAST_MODE" = "1" ]; then
  if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
    fix_node_load_nvm
    nvm use "$(fix_node_requested_version)" >/dev/null 2>&1 || true
    hash -r
  fi
elif [ "$FAST_MODE" != "1" ]; then
  ensure_zeinaguard_node_toolchain
fi

if [ "$FAST_MODE" = "1" ]; then
  [ -d "$ROOT_DIR/node_modules" ] || { echo "[ERROR] Fast mode requires existing node_modules"; exit 1; }
  echo "[SKIP] Frontend dependency install skipped (--fast)"
else
  current_lock_hash="$(sha256_file "$LOCK_FILE")"
  saved_lock_hash=""
  if [ -f "$LOCK_HASH_FILE" ]; then
    saved_lock_hash="$(tr -d '[:space:]' < "$LOCK_HASH_FILE")"
  fi

  if [ -d "$ROOT_DIR/node_modules" ] && [ "$current_lock_hash" = "$saved_lock_hash" ]; then
    echo "[SKIP] Frontend dependencies already installed"
  else
    echo "[frontend] Installing dependencies with pnpm..."
    cd "$ROOT_DIR"
    pnpm install
    mkdir -p "$ROOT_DIR/node_modules"
    printf '%s\n' "$current_lock_hash" > "$LOCK_HASH_FILE"
  fi
fi

cd "$ROOT_DIR"
echo "[frontend] Starting dev server..."
exec pnpm dev
