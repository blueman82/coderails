#!/bin/bash
# Thin exec wrapper for launchd (see launchd/com.coderails.routine-sweeper.*.plist
# in WU4). launchd's env carries no PATH (verified via `launchctl print
# gui/$UID` 2026-07-06), so this script and the plists that invoke it use
# absolute paths throughout — never a bare `node` or `npm` command.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /opt/homebrew/bin/node "$SCRIPT_DIR/../dist/main.js"
