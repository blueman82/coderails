#!/bin/bash
# Idempotent uninstall: bootout the dashboard plist from the user's gui
# domain and remove the ~/Library/LaunchAgents/ copy that
# install-dashboard-agent.sh placed there (so the job doesn't auto-load at
# the next login). Works whether the install was new-style (LaunchAgents
# copy present) or old-style (repo-path bootstrap, no copy) — the copy
# removal is a no-op if the copy is absent.
set -euo pipefail
UID_DOMAIN="gui/$(id -u)"
LABEL="com.coderails.dashboard"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "$UID_DOMAIN/$LABEL" 2>/dev/null || true

if launchctl print "$UID_DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Error: $LABEL is still loaded after bootout" >&2
  exit 1
fi

rm -f "$DEST"

echo "Uninstalled (or was already absent): $LABEL"
