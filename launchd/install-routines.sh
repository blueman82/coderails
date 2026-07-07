#!/bin/bash
# Idempotent install: bootstrap both plists into the user's gui domain.
# Uses `launchctl bootstrap` (modern API, cleanly errors on a bad plist)
# rather than the legacy `load` command.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"

for plist in "$SCRIPT_DIR"/com.coderails.routine-sweeper.*.plist; do
  label=$(basename "$plist" .plist)
  # Idempotent: bootout first (ignore "not found" errors), then bootstrap
  # fresh — avoids "already bootstrapped" failures on re-install.
  launchctl bootout "$UID_DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$UID_DOMAIN" "$plist"
  echo "Installed: $label"
done
