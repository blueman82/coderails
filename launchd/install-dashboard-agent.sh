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
# ~/.claude/coderails-dashboard/dashboard.log. This mkdir guarantees the log
# dir exists with tight perms before launchd ever tries to write to it; the
# chmod covers a dir that already exists at a looser mode from an earlier
# manual run (mkdir -p only sets mode on creation).
mkdir -p -m 0700 "$HOME/.claude/coderails-dashboard"
chmod 700 "$HOME/.claude/coderails-dashboard"

# Fail loudly if a manually-started dashboard already holds the port, rather
# than bootstrapping an agent that will just crash-loop on EADDRINUSE every
# ThrottleInterval — see skills/dashboard/scripts/start-dashboard.sh for the
# same guard on the manual-start side.
if holder="$(lsof -nP -iTCP:4173 -sTCP:LISTEN 2>/dev/null)" && [[ -n "$holder" ]]; then
  echo "Port 4173 is already in use by another process:" >&2
  echo "$holder" >&2
  echo "Stop the manually-started dashboard first (bash skills/dashboard/scripts/stop-dashboard.sh), or the agent will crash-loop every 60s on EADDRINUSE." >&2
  exit 1
fi

echo "Installing: $LABEL ($PLIST)"
# Idempotent: bootout first (ignore "not found" errors), then bootstrap
# fresh — avoids "already bootstrapped" failures on re-install.
launchctl bootout "$UID_DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$UID_DOMAIN" "$PLIST"
echo "Installed: $LABEL"
