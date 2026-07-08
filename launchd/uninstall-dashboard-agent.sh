#!/bin/bash
# Idempotent uninstall: bootout the dashboard plist from the user's gui
# domain.
set -euo pipefail
UID_DOMAIN="gui/$(id -u)"
LABEL="com.coderails.dashboard"

launchctl bootout "$UID_DOMAIN/$LABEL" 2>/dev/null || true

if launchctl print "$UID_DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Error: $LABEL is still loaded after bootout" >&2
  exit 1
fi

echo "Uninstalled (or was already absent): $LABEL"
