#!/bin/bash
# Guard test: the dashboard's launchd LaunchAgent (bin/dashboard-server.sh,
# launchd/com.coderails.dashboard.plist, and the install/uninstall pair)
# must follow the same absolute-path, foreground-exec, idempotent-install
# conventions the routine-sweeper agents already established — see
# docs/routines.md and launchd/install-routines.sh's own header comments
# for why: launchd's env carries no PATH (verified via `launchctl print
# gui/$UID`), so a bare `npm`/`node` command or a backgrounded/PID-file
# process would silently misbehave under the scheduler.
#
# Usage: bash dashboard_agent.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
WRAPPER="$REPO_ROOT/skills/dashboard/runner/bin/dashboard-server.sh"
PLIST="$REPO_ROOT/launchd/com.coderails.dashboard.plist"
INSTALL="$REPO_ROOT/launchd/install-dashboard-agent.sh"
UNINSTALL="$REPO_ROOT/launchd/uninstall-dashboard-agent.sh"

fails=0
checks=0
check() { # desc expected actual
  checks=$((checks+1))
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- wrapper: exists, executable, no relative-PATH commands ---
check "wrapper exists" "yes" "$([ -f "$WRAPPER" ] && echo yes || echo no)"
check "wrapper is executable" "yes" "$([ -x "$WRAPPER" ] && echo yes || echo no)"

# The wrapper must `exec` its server process (launchd owns the surviving PID
# directly) rather than backgrounding it with `nohup ... &` or writing a
# PID file the way start-dashboard.sh does — that pattern exists precisely
# because a foreground shell session needs to hand control back; a launchd
# agent has no such need and a background+PID-file here would just leave
# launchd babysitting an empty shell wrapper instead of the real server.
check "wrapper execs the server (no backgrounding)" "yes" \
  "$(grep -qE '^\s*exec\s' "$WRAPPER" 2>/dev/null && echo yes || echo no)"
check "wrapper does not background with nohup/&" "yes" \
  "$(! grep -qE 'nohup|&\s*$' "$WRAPPER" 2>/dev/null && echo yes || echo no)"
check "wrapper does not write a PID file" "yes" \
  "$(! grep -qE 'PID_FILE|\.pid' "$WRAPPER" 2>/dev/null && echo yes || echo no)"

# launchd's env carries no PATH, so npm/node must be invoked by absolute
# path, and PATH itself must be exported so npm's internal shell-outs work.
check "wrapper exports PATH with /opt/homebrew/bin" "yes" \
  "$(grep -qE 'export PATH=.*opt/homebrew/bin' "$WRAPPER" 2>/dev/null && echo yes || echo no)"

# --- plist: well-formed XML + required keys ---
check "plist exists" "yes" "$([ -f "$PLIST" ] && echo yes || echo no)"
check "plist is well-formed XML" "yes" \
  "$(plutil -lint "$PLIST" >/dev/null 2>&1 && echo yes || echo no)"
check "plist Label is com.coderails.dashboard" "yes" \
  "$(grep -A1 '<key>Label</key>' "$PLIST" | grep -q 'com.coderails.dashboard' && echo yes || echo no)"
for key in RunAtLoad KeepAlive ThrottleInterval Label StandardOutPath StandardErrorPath ProgramArguments; do
  check "plist has key $key" "yes" \
    "$(grep -q "<key>$key</key>" "$PLIST" 2>/dev/null && echo yes || echo no)"
done
check "plist RunAtLoad is true" "yes" \
  "$(grep -A1 '<key>RunAtLoad</key>' "$PLIST" | grep -q '<true/>' && echo yes || echo no)"
check "plist KeepAlive is true" "yes" \
  "$(grep -A1 '<key>KeepAlive</key>' "$PLIST" | grep -q '<true/>' && echo yes || echo no)"
check "plist ThrottleInterval is 60" "yes" \
  "$(grep -A1 '<key>ThrottleInterval</key>' "$PLIST" | grep -q '<integer>60</integer>' && echo yes || echo no)"
check "plist ProgramArguments references the wrapper" "yes" \
  "$(grep -q 'skills/dashboard/runner/bin/dashboard-server.sh' "$PLIST" 2>/dev/null && echo yes || echo no)"
check "plist logs to dashboard.log" "yes" \
  "$(grep -q 'coderails-dashboard/dashboard.log' "$PLIST" 2>/dev/null && echo yes || echo no)"

# --- install/uninstall: exist, executable, idempotent, reference the plist ---
check "install script exists" "yes" "$([ -f "$INSTALL" ] && echo yes || echo no)"
check "install script is executable" "yes" "$([ -x "$INSTALL" ] && echo yes || echo no)"
check "uninstall script exists" "yes" "$([ -f "$UNINSTALL" ] && echo yes || echo no)"
check "uninstall script is executable" "yes" "$([ -x "$UNINSTALL" ] && echo yes || echo no)"

check "install script references com.coderails.dashboard.plist" "yes" \
  "$(grep -q 'com.coderails.dashboard' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "uninstall script references com.coderails.dashboard.plist" "yes" \
  "$(grep -q 'com.coderails.dashboard' "$UNINSTALL" 2>/dev/null && echo yes || echo no)"

# Idempotent install: bootout (ignore failure) before bootstrap, same
# ordering as install-routines.sh, so a re-run never fails on
# "already bootstrapped".
check "install script boots out before bootstrapping" "yes" \
  "$(awk '/launchctl bootout/{bo=NR} /launchctl bootstrap/{bs=NR} END{print (bo && bs && bo<bs) ? "yes" : "no"}' "$INSTALL")"
check "install script tolerates bootout failure (|| true)" "yes" \
  "$(grep -qE 'launchctl bootout.*\|\|\s*true' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "uninstall script tolerates bootout failure (|| true)" "yes" \
  "$(grep -qE 'launchctl bootout.*\|\|\s*true' "$UNINSTALL" 2>/dev/null && echo yes || echo no)"

# install-dashboard-agent.sh must not widen the routine-sweeper scripts'
# glob (install-routines.sh's glob is routine-sweeper-specific, a separate
# concern from the dashboard server agent).
check "install-routines.sh glob is unchanged (routine-sweeper only)" "yes" \
  "$(grep -q 'com.coderails.routine-sweeper' "$REPO_ROOT/launchd/install-routines.sh" 2>/dev/null && ! grep -q 'com.coderails.dashboard' "$REPO_ROOT/launchd/install-routines.sh" 2>/dev/null && echo yes || echo no)"

if [ "$checks" -eq 0 ]; then
  echo "FAIL - zero checks ran — guard is vacuous"
  exit 1
fi

[ "$fails" -eq 0 ] && { echo "PASS ($checks check(s))"; exit 0; } || { echo "FAILED ($fails/$checks)"; exit 1; }
