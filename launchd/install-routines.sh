#!/bin/bash
# Idempotent install: bootstrap both plists into the user's gui domain.
# Uses `launchctl bootstrap` (modern API, cleanly errors on a bad plist)
# rather than the legacy `load` command.
#
# NOTE: both plists' ProgramArguments and log paths are machine-specific
# absolute paths (e.g. /Users/harrison/Github/coderails/...) baked in at
# plist-authoring time, not derived from this script's own SCRIPT_DIR or the
# installing user's home — these plists are not portable to another
# checkout location or another user's machine as-is (I5).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"

# Both plists' StandardOutPath/StandardErrorPath point at
# ~/.claude/coderails-dashboard/routines/sweeper.log. Without this, launchd
# would create that directory itself on first log write, at the process's
# default umask — potentially group/world-readable. Routine output can
# include skill/artifact content, so create it with 0700 upfront (I5).
mkdir -p -m 0700 "$HOME/.claude/coderails-dashboard/routines"

for plist in "$SCRIPT_DIR"/com.coderails.routine-sweeper.*.plist; do
  label=$(basename "$plist" .plist)
  echo "Installing: $label ($plist)"
  # Idempotent: bootout first (ignore "not found" errors), then bootstrap
  # fresh — avoids "already bootstrapped" failures on re-install.
  launchctl bootout "$UID_DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$UID_DOMAIN" "$plist"
  echo "Installed: $label"
done
