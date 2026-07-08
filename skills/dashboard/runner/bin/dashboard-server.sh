#!/bin/bash
# Thin exec wrapper for launchd (see
# launchd/com.coderails.dashboard.plist). launchd's env carries no PATH
# (verified via `launchctl print gui/$UID` — see docs/routines.md and
# bin/sweeper.sh's header for the same finding), so this script uses
# absolute paths throughout and exports PATH itself so npm's internal
# shell-outs (which do rely on PATH) still work.
#
# Unlike scripts/start-dashboard.sh, this wrapper execs npm in the
# foreground (npm forwards SIGTERM to the next server); never backgrounds,
# never writes a PID file.
set -euo pipefail

# ~/.local/bin carries the `claude` CLI the approve->build wrapper invokes;
# launchd's empty PATH omits it, so a daemon-spawned build died
# "claude: command not found" until it was added here.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
APP_DIR="$(cd "$DASHBOARD_DIR/app" && pwd)"
REPO_ROOT="$(cd "$DASHBOARD_DIR/../.." && pwd)"

# The approve->build route spawns run-builder.sh, which hard-requires
# CODERAILS_BUILDER_REPO_PATH (aborts on its `:?` guard otherwise) and uses
# CODERAILS_BUILDER_WRAPPER to locate itself under the production bundle
# where __dirname is virtualised. launchd's env carries neither, so every
# real Approve failed unexpected_exit:1 until these were exported here.
# Both absolute, derived from this checkout, surviving the scheduler's
# empty env.
export CODERAILS_BUILDER_REPO_PATH="$REPO_ROOT"
export CODERAILS_BUILDER_WRAPPER="$DASHBOARD_DIR/scripts/run-builder.sh"

cd "$APP_DIR"

# launchd can't write the log if the dir was deleted; this heals every
# respawn after the first.
mkdir -p -m 0700 "$HOME/.claude/coderails-dashboard"
chmod 700 "$HOME/.claude/coderails-dashboard"

if [[ ! -d node_modules ]] || [[ ! -f node_modules/.package-lock.json ]]; then
  npm ci
fi

# Rebuild if there's no prior build, no src dir, any src file is newer than
# the existing build output, or dependency/config files changed — this
# extends start-dashboard.sh's check with a fail-safe + dependency/config
# staleness, because no human watches a daemon to notice a stale build.
NEED_BUILD="false"
if [[ ! -d .next ]] || [[ ! -d src ]]; then
  NEED_BUILD="true"
elif [[ -n "$(find src -newer .next -type f -print -quit)" ]]; then
  NEED_BUILD="true"
elif [[ -n "$(find package.json package-lock.json next.config.mjs -newer .next -print -quit)" ]]; then
  NEED_BUILD="true"
fi

if [[ "$NEED_BUILD" == "true" ]]; then
  npm run build
fi

exec npm run start -- --hostname 127.0.0.1 --port 4173
