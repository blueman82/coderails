#!/bin/bash
# Idempotent install: bootstrap the dashboard plist into the user's gui
# domain. Uses `launchctl bootstrap` (modern API, cleanly errors on a bad
# plist) rather than the legacy `load` command. Sibling to
# install-routines.sh, kept separate because it drives a different agent
# (the dashboard web server, not the routine sweeper).
#
# NOTE: the plist's ProgramArguments and log path are machine-specific
# absolute paths (e.g. /Users/harrison/Github/coderails/...) baked in at
# plist-authoring time, not derived from this script's own SCRIPT_DIR or the
# installing user's home — this plist is not portable to another checkout
# location or another user's machine as-is.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"
PLIST="$SCRIPT_DIR/com.coderails.dashboard.plist"
LABEL="com.coderails.dashboard"

# StandardOutPath/StandardErrorPath point at
# ~/.claude/coderails-dashboard/dashboard.log. Without this, launchd would
# create that directory itself on first log write, at the process's default
# umask — potentially group/world-readable.
mkdir -p -m 0700 "$HOME/.claude/coderails-dashboard"

echo "Installing: $LABEL ($PLIST)"
# Idempotent: bootout first (ignore "not found" errors), then bootstrap
# fresh — avoids "already bootstrapped" failures on re-install.
launchctl bootout "$UID_DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$UID_DOMAIN" "$PLIST"
echo "Installed: $LABEL"
