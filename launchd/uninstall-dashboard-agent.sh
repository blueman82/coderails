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

bootout_err="$(launchctl bootout "$UID_DOMAIN/$LABEL" 2>&1 >/dev/null || true)"

# bootout is asynchronous for a running KeepAlive job: it returns before the
# job has actually unloaded (observed live 2026-07-08 — a running KeepAlive
# job unloaded ~2s after bootout returned). Poll for up to 10s before
# declaring failure, rather than checking once immediately and erroring out
# spuriously on a job that is mid-teardown.
still_loaded=1
for _ in $(seq 1 10); do
  if ! launchctl print "$UID_DOMAIN/$LABEL" >/dev/null 2>&1; then
    still_loaded=0
    break
  fi
  sleep 1
done

if [ "$still_loaded" -eq 1 ]; then
  echo "Error: $LABEL is still loaded after bootout" >&2
  [ -n "$bootout_err" ] && echo "bootout said: $bootout_err" >&2
  echo "Leaving $DEST in place (job still loaded, not safe to remove)" >&2
  exit 1
fi

rm -f "$DEST"

echo "Uninstalled (or was already absent): $LABEL"
