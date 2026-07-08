#!/bin/bash
# Idempotent uninstall: bootout the dashboard plist from the user's gui
# domain.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"
LABEL="com.coderails.dashboard"

launchctl bootout "$UID_DOMAIN/$LABEL" 2>/dev/null || true
echo "Uninstalled (or was already absent): $LABEL"
