#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${TMPDIR:-/tmp}/mutual-fund-faq"
cd "$ROOT_DIR"
mkdir -p "$STATE_DIR"

exec 9>"$STATE_DIR/startup.lock"
flock 9

port_is_listening() {
  timeout 1 bash -c ": </dev/tcp/127.0.0.1/$1" >/dev/null 2>&1
}

start_if_needed() {
  local port="$1"
  local name="$2"
  shift 2

  local pid_file="$STATE_DIR/$name.pid"
  local log_file="$STATE_DIR/$name.log"

  if port_is_listening "$port"; then
    printf '%s already listening on 127.0.0.1:%s\n' "$name" "$port"
    return
  fi

  if [[ -f "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
    printf '%s is already starting (pid %s)\n' "$name" "$(<"$pid_file")"
    return
  fi

  nohup "$@" >>"$log_file" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$pid_file"
  printf '%s started (pid %s); log: %s\n' "$name" "$!" "$log_file"
}

start_if_needed 8000 api python src/api.py
start_if_needed 8001 ui python src/ui_server.py