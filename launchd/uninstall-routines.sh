#!/bin/bash
# Idempotent uninstall: bootout both plists from the user's gui domain.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"

for plist in "$SCRIPT_DIR"/com.coderails.routine-sweeper.*.plist; do
  label=$(basename "$plist" .plist)
  launchctl bootout "$UID_DOMAIN/$label" 2>/dev/null || true
  echo "Uninstalled (or was already absent): $label"
done
