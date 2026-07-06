#!/usr/bin/env bash
# Start the coderails observability dashboard (production server) and open it
# in the browser.
# Usage: start-dashboard.sh
#
# Env overrides:
#   DASHBOARD_PORT   Port to serve on (default: 4173).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_DIR/../app" && pwd)"
STATE_DIR="$HOME/.claude/coderails-dashboard"
PID_FILE="$STATE_DIR/dashboard.pid"
LOG_FILE="$STATE_DIR/dashboard.log"
PORT="${DASHBOARD_PORT:-4173}"
HOST="127.0.0.1"

mkdir -p "$STATE_DIR"

cd "$APP_DIR"

if [[ ! -d node_modules ]]; then
  echo "Installing dependencies (npm ci)..."
  npm ci
fi

# Rebuild if there's no prior build, or if any source file is newer than the
# existing build output.
NEED_BUILD="false"
if [[ ! -d .next ]]; then
  NEED_BUILD="true"
elif [[ -n "$(find src -newer .next -type f -print -quit 2>/dev/null)" ]]; then
  NEED_BUILD="true"
fi

if [[ "$NEED_BUILD" == "true" ]]; then
  echo "Building dashboard (npm run build)..."
  npm run build
fi

# If a previous instance is still alive, stop it before starting a new one.
if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$old_pid" 2>/dev/null || break
      sleep 0.1
    done
  fi
  rm -f "$PID_FILE"
fi

# Fail loudly if some other process already holds the port, rather than
# starting a doomed child and later mistaking that foreign process's
# response for our own server's readiness.
if holder="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null)" && [[ -n "$holder" ]]; then
  echo "Port $PORT is already in use by another process:" >&2
  echo "$holder" >&2
  exit 1
fi

nohup npm run start -- --hostname "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
disown "$SERVER_PID" 2>/dev/null || true
echo "$SERVER_PID" > "$PID_FILE"

URL="http://${HOST}:${PORT}"

# Wait for the server to accept connections.
READY="false"
for _ in {1..50}; do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "Dashboard server exited early. See $LOG_FILE" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  if curl -s -o /dev/null "$URL" 2>/dev/null; then
    READY="true"
    break
  fi
  sleep 0.2
done

if [[ "$READY" != "true" ]]; then
  echo "Dashboard did not become ready within 10s. See $LOG_FILE" >&2
  exit 1
fi

# A 200 response doesn't by itself prove our server answered it — confirm
# our child is still the one alive before declaring success.
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "Dashboard server exited after reporting ready. See $LOG_FILE" >&2
  rm -f "$PID_FILE"
  exit 1
fi

echo "Dashboard running at $URL (pid $SERVER_PID)"
open "$URL" 2>/dev/null || true
