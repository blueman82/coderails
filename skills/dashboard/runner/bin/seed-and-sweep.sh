#!/bin/bash
# Thin exec wrapper for launchd's CALENDAR plist (see
# launchd/com.coderails.routine-sweeper.calendar.plist in WU4). Runs the
# seed step (drops one intent per due routine into queue/, see
# src/seed.ts's header) and then the same sweep bin/sweeper.sh invokes,
# so the calendar trigger actually produces work for the sweeper to do —
# see src/seed.ts and src/seedMain.ts for why seeding exists as a
# producer rather than a sweep.ts/main.ts change. The WATCH plist keeps
# invoking bin/sweeper.sh directly (unchanged): a button press already
# writes its own intent, so the watch path needs no seeding step.
#
# launchd's env carries no PATH (verified via `launchctl print gui/$UID`
# 2026-07-06), so this script uses absolute paths throughout — never a
# bare `node` command. Node 24's built-in TypeScript type-stripping runs
# src/*.ts files directly with no build step (verified in this worktree —
# skills/dashboard/runner has no dist/ output today; bin/sweeper.sh's own
# `dist/main.js` reference is a pre-existing gap in the merged WU2 code,
# not something this script repeats).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
/opt/homebrew/bin/node "$SCRIPT_DIR/../src/seedMain.ts"
exec /opt/homebrew/bin/node "$SCRIPT_DIR/../src/main.ts"
