#!/bin/bash
# Idempotent install: copy both plists into ~/Library/LaunchAgents/ and
# bootstrap them into the user's gui domain from that copy. Uses `launchctl
# bootstrap` (modern API, cleanly errors on a bad plist) rather than the
# legacy `load` command.
#
# The copy step is load-bearing: a `launchctl bootstrap` from an arbitrary
# path (e.g. this repo dir) only survives until logout/reboot. launchd only
# auto-loads plists that live in ~/Library/LaunchAgents/, so bootstrapping
# from the repo path silently unloads the entire routines system on the next
# reboot (observed live 2026-07-08: 03:00 run fine, reboot at 07:34, no
# com.coderails jobs afterwards). Bootstrapping from the LaunchAgents copy
# makes the jobs auto-load at every login.
#
# NOTE: both plists' ProgramArguments and log paths are machine-specific
# absolute paths (e.g. /Users/harrison/Github/coderails/...) baked in at
# plist-authoring time, not derived from this script's own SCRIPT_DIR or the
# installing user's home — these plists are not portable to another
# checkout location or another user's machine as-is (I5). Copying them into
# LaunchAgents does not change that: the baked-in paths still point back at
# this checkout.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UID_DOMAIN="gui/$(id -u)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"

# Both plists' StandardOutPath/StandardErrorPath point at
# ~/.claude/coderails-dashboard/routines/sweeper.log. Without this, launchd
# would create that directory itself on first log write, at the process's
# default umask — potentially group/world-readable. Routine output can
# include skill/artifact content, so create it with 0700 upfront (I5).
mkdir -p -m 0700 "$HOME/.claude/coderails-dashboard/routines"

mkdir -p "$LAUNCH_AGENTS"

# nullglob so an empty match expands to nothing rather than the literal
# pattern (which, under `set -e`, would crash `install` with a cryptic
# "No such file" mid-loop). The guard then turns "no plists" into a clear error.
shopt -s nullglob
plists=("$SCRIPT_DIR"/com.coderails.routine-sweeper.*.plist)
if [ "${#plists[@]}" -eq 0 ]; then
  echo "Error: no com.coderails.routine-sweeper.*.plist found in $SCRIPT_DIR" >&2
  exit 1
fi

for plist in "${plists[@]}"; do
  label=$(basename "$plist" .plist)
  dest="$LAUNCH_AGENTS/$label.plist"
  echo "Installing: $label ($plist)"
  # Copy into LaunchAgents so launchd auto-loads it at login/reboot. 0644 is
  # the standard mode for a LaunchAgent plist (it's not secret, and launchd
  # reads it as the user).
  install -m 0644 "$plist" "$dest"
  # Idempotent: bootout first (ignore "not found" errors), then bootstrap
  # fresh from the LaunchAgents copy — avoids "already bootstrapped" failures
  # on re-install.
  launchctl bootout "$UID_DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$UID_DOMAIN" "$dest"
  echo "Installed: $label"
done
