#!/bin/bash
# Thin exec wrapper for launchd (see launchd/com.coderails.routine-sweeper.*.plist
# in WU4). launchd's env carries no PATH (verified via `launchctl print
# gui/$UID` 2026-07-06), so this script and the plists that invoke it use
# absolute paths throughout — never a bare `node` or `npm` command.
#
# Runs src/main.ts directly via Node 24's built-in TypeScript type-stripping
# (no build step) — matches bin/seed-and-sweep.sh's proven-working pattern.
# The previous ../dist/main.js target never existed (no build step produces
# dist/, and dist/ is gitignored), so every watch-plist fire died
# MODULE_NOT_FOUND with only the sweeper.log to show for it (C2).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /opt/homebrew/bin/node "$SCRIPT_DIR/../src/main.ts"
