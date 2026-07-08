#!/bin/bash
# Idempotent uninstall: bootout both plists from the user's gui domain and
# remove the ~/Library/LaunchAgents/ copies that install-routines.sh placed
# there (so the jobs don't auto-load at the next login). Works whether the
# install was new-style (LaunchAgents copy present) or old-style (repo-path
# bootstrap, no copy) — the copy removal is a no-op if the copy is absent.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

for plist in "$SCRIPT_DIR"/com.coderails.routine-sweeper.*.plist; do
  label=$(basename "$plist" .plist)
  launchctl bootout "$UID_DOMAIN/$label" 2>/dev/null || true
  rm -f "$LAUNCH_AGENTS/$label.plist"
  echo "Uninstalled (or was already absent): $label"
done
