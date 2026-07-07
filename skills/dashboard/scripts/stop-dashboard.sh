#!/usr/bin/env bash
# Stop the coderails observability dashboard started by start-dashboard.sh.
# Usage: stop-dashboard.sh
set -euo pipefail

STATE_DIR="$HOME/.claude/coderails-dashboard"
PID_FILE="$STATE_DIR/dashboard.pid"

# PID-reuse guard: only treat the pid as ours if its command line looks like
# the dashboard server (npm run start / next / node). Anything else means the
# OS recycled the pid for an unrelated process — the pid file is stale.
pid_is_dashboard() {
  local cmd
  cmd="$(ps -p "$1" -o command= 2>/dev/null || true)"
  case "$cmd" in
    *"npm run start"*|*next*|*node*) return 0 ;;
    *) return 1 ;;
  esac
}

if [[ ! -f "$PID_FILE" ]]; then
  echo '{"status": "not_running"}'
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"

if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo '{"status": "stale_pid"}'
  exit 0
fi

if ! pid_is_dashboard "$pid"; then
  rm -f "$PID_FILE"
  echo '{"status": "stale_pid"}'
  exit 0
fi

kill "$pid" 2>/dev/null || true

for _ in {1..20}; do
  kill -0 "$pid" 2>/dev/null || break
  sleep 0.1
done

if kill -0 "$pid" 2>/dev/null; then
  kill -9 "$pid" 2>/dev/null || true
  sleep 0.1
fi

if kill -0 "$pid" 2>/dev/null; then
  echo '{"status": "failed", "error": "process still running"}'
  exit 1
fi

rm -f "$PID_FILE"
echo '{"status": "stopped"}'
