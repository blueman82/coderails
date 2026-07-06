#!/usr/bin/env bash
# Stop the coderails observability dashboard started by start-dashboard.sh.
# Usage: stop-dashboard.sh
set -euo pipefail

STATE_DIR="$HOME/.claude/coderails-dashboard"
PID_FILE="$STATE_DIR/dashboard.pid"

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
