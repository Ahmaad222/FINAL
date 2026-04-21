#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$ROOT_DIR/logs"

FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

log() {
  printf '[stop_all] %s\n' "$*"
}

warn() {
  printf '[stop_all][warn] %s\n' "$*" >&2
}

pid_file_for() {
  printf '%s/%s.pid\n' "$LOG_DIR" "$1"
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

process_running() {
  local pid="$1"
  local state=""

  [ -n "$pid" ] || return 1
  state="$(ps -o stat= -p "$pid" 2>/dev/null | awk 'NR==1 {print $1}')"
  [ -n "$state" ] && [[ "$state" != Z* ]]
}

signal_pid() {
  local signal_name="$1"
  local pid="$2"

  [ -n "$pid" ] || return 0

  if kill "-${signal_name}" "$pid" >/dev/null 2>&1; then
    return 0
  fi

  if command_exists sudo; then
    sudo -n kill "-${signal_name}" "$pid" >/dev/null 2>&1 || true
  fi
}

signal_process_group() {
  local signal_name="$1"
  local pid="$2"

  [ -n "$pid" ] || return 0

  if kill "-${signal_name}" -- "-$pid" >/dev/null 2>&1; then
    return 0
  fi

  if command_exists sudo; then
    sudo -n kill "-${signal_name}" -- "-$pid" >/dev/null 2>&1 || true
  fi
}

wait_for_exit() {
  local pid="$1"
  local timeout_seconds="${2:-10}"
  local elapsed=0

  while process_running "$pid" && [ "$elapsed" -lt "$timeout_seconds" ]; do
    sleep 1
    elapsed=$((elapsed + 1))
  done

  ! process_running "$pid"
}

terminate_pid() {
  local pid="$1"
  local label="$2"

  [ -n "$pid" ] || return 0
  if ! process_running "$pid"; then
    return 0
  fi

  log "Stopping $label (pid $pid)"
  signal_process_group TERM "$pid"
  signal_pid TERM "$pid"

  if wait_for_exit "$pid" 10; then
    return 0
  fi

  warn "$label did not stop gracefully; forcing shutdown"
  signal_process_group KILL "$pid"
  signal_pid KILL "$pid"
  wait_for_exit "$pid" 5 || true
}

stop_service_from_pid_file() {
  local service_name="$1"
  local pid_file
  local pid=""

  pid_file="$(pid_file_for "$service_name")"
  if [ ! -f "$pid_file" ]; then
    return
  fi

  pid="$(tr -d '[:space:]' <"$pid_file" || true)"
  terminate_pid "$pid" "$service_name"
  rm -f "$pid_file"
}

port_listeners() {
  local port="$1"

  if command_exists fuser; then
    fuser -n tcp "$port" 2>/dev/null || true
    return
  fi

  if command_exists lsof; then
    lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null || true
    return
  fi
}

cleanup_port() {
  local port="$1"
  local listeners=""

  listeners="$(port_listeners "$port")"
  [ -n "$listeners" ] || return 0

  log "Cleaning up processes still bound to port $port"
  if command_exists fuser; then
    fuser -k -TERM -n tcp "$port" >/dev/null 2>&1 || true
    sleep 2
    if [ -n "$(port_listeners "$port")" ]; then
      fuser -k -KILL -n tcp "$port" >/dev/null 2>&1 || true
      sleep 1
    fi
  elif command_exists lsof; then
    while read -r pid; do
      [ -n "$pid" ] || continue
      kill -TERM "$pid" >/dev/null 2>&1 || true
    done <<<"$listeners"
    sleep 2
  else
    warn "Neither fuser nor lsof is available; port cleanup skipped for $port"
    return 0
  fi

  [ -z "$(port_listeners "$port")" ] || warn "Port $port is still busy after cleanup"
}

main() {
  mkdir -p "$LOG_DIR"

  stop_service_from_pid_file "sensor"
  stop_service_from_pid_file "backend"
  stop_service_from_pid_file "frontend"

  cleanup_port "$BACKEND_PORT"
  cleanup_port "$FRONTEND_PORT"

  log "ZeinaGuard Pro services have been stopped"
}

main "$@"
