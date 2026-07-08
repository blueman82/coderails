#!/bin/bash
# Thin exec wrapper for launchd (see
# launchd/com.coderails.dashboard.plist). launchd's env carries no PATH
# (verified via `launchctl print gui/$UID` — see docs/routines.md and
# bin/sweeper.sh's header for the same finding), so this script uses
# absolute paths throughout and exports PATH itself so npm's internal
# shell-outs (which do rely on PATH) still work.
#
# Unlike scripts/start-dashboard.sh, this wrapper never backgrounds the
# server or writes a PID file — launchd itself needs to own the surviving
# PID to restart it on crash (KeepAlive) or track it at all, so the final
# server process is `exec`'d in the foreground, replacing this script.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
APP_DIR="$(cd "$DASHBOARD_DIR/app" && pwd)"

cd "$APP_DIR"

if [[ ! -d node_modules ]]; then
  npm ci
fi

# Rebuild if there's no prior build, or if any source file is newer than the
# existing build output — same staleness check as start-dashboard.sh.
NEED_BUILD="false"
if [[ ! -d .next ]]; then
  NEED_BUILD="true"
elif [[ -n "$(find src -newer .next -type f -print -quit 2>/dev/null)" ]]; then
  NEED_BUILD="true"
fi

if [[ "$NEED_BUILD" == "true" ]]; then
  npm run build
fi

exec npm run start -- --hostname 127.0.0.1 --port 4173
