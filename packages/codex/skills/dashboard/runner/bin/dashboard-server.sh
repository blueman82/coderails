#!/bin/bash
# On-demand dashboard wrapper. It uses absolute paths and exports PATH so
# npm's internal shell-outs work even when the caller has a minimal environment.
#
# Unlike scripts/start-dashboard.sh, this wrapper execs npm in the
# foreground (npm forwards SIGTERM to the next server); never backgrounds,
# never writes a PID file.
set -euo pipefail

# ~/.local/bin carries the `codex` CLI the approve->build wrapper invokes.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
APP_DIR="$(cd "$DASHBOARD_DIR/app" && pwd)"
REPO_ROOT="$(cd "$DASHBOARD_DIR/../../../.." && pwd)"

# The approve->build route spawns run-builder.sh, which hard-requires
# CODERAILS_BUILDER_REPO_PATH (aborts on its `:?` guard otherwise) and uses
# CODERAILS_BUILDER_WRAPPER to locate itself under the production bundle
# where __dirname is virtualised. Export both as absolute paths derived from
# this checkout so the wrapper does not depend on inherited variables.
export CODERAILS_BUILDER_REPO_PATH="$REPO_ROOT"
export CODERAILS_BUILDER_WRAPPER="$DASHBOARD_DIR/scripts/run-builder.sh"

cd "$APP_DIR"

# Recreate the state directory if it was deleted between on-demand starts.
mkdir -p "$HOME/.codex/coderails-dashboard"
chmod 700 "$HOME/.codex/coderails-dashboard"

if [[ ! -d node_modules ]] || [[ ! -f node_modules/.package-lock.json ]]; then
    npm ci
fi

# Rebuild if there's no prior build, no src dir, any src file is newer than
# the existing build output, or dependency/config files changed — this
# extends start-dashboard.sh's check with fail-safe dependency/config
# staleness detection.
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

# Accept only loopback shortcuts or a concrete IP literal — the request guard
# exact-matches ONE host, so a wildcard bind, a host:port form, or a hostname
# would silently 403 real LAN requests. Empty/unset DASHBOARD_HOST is fine
# (falls through to the loopback default below).
# Reject invalid values immediately so the caller sees the misconfiguration.
if [[ -n "${DASHBOARD_HOST:-}" ]]; then
    case "$DASHBOARD_HOST" in
    localhost | 127.0.0.1 | ::1) ;;
    0.0.0.0 | :: | '*')
        echo "DASHBOARD_HOST='$DASHBOARD_HOST' is not a concrete host IP (wildcards like 0.0.0.0 and host:port forms are rejected — the guard exact-matches one host; see SKILL.md)" >&2
        exit 1
        ;;
    *)
        if [[ "$DASHBOARD_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$ ]]; then
            echo "DASHBOARD_HOST='$DASHBOARD_HOST' is not a concrete host IP (wildcards like 0.0.0.0 and host:port forms are rejected — the guard exact-matches one host; see SKILL.md)" >&2
            exit 1
        elif [[ "$DASHBOARD_HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            : # concrete IPv4 literal — accept
        elif [[ "$DASHBOARD_HOST" == *:* ]]; then
            : # bare IPv6 literal — accept
        else
            echo "DASHBOARD_HOST='$DASHBOARD_HOST' is not a concrete host IP (wildcards like 0.0.0.0 and host:port forms are rejected — the guard exact-matches one host; see SKILL.md)" >&2
            exit 1
        fi
        ;;
    esac
fi

exec npm run start -- --hostname "${DASHBOARD_HOST:-127.0.0.1}" --port 4173
