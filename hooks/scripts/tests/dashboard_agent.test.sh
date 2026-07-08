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
# It must also copy the plist into ~/Library/LaunchAgents/ and bootstrap
# from that copy rather than the repo path — a `launchctl bootstrap` from an
# arbitrary path only survives until logout/reboot, launchd only auto-loads
# plists that live in ~/Library/LaunchAgents/. The routine-sweeper agents hit
# this live on 2026-07-08 (03:00 run fine, reboot at 07:34, every
# com.coderails job silently gone); install-routines.sh's fix (copy-then-
# bootstrap-from-copy) is the pattern this installer must mirror.
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

# --- wrapper: exists, executable, execs in the foreground ---
check "wrapper exists" "yes" "$([ -f "$WRAPPER" ] && echo yes || echo no)"
check "wrapper is executable" "yes" "$([ -x "$WRAPPER" ] && echo yes || echo no)"

# The wrapper must `exec` its server process (it execs npm in the foreground,
# which forwards SIGTERM to the next server) rather than backgrounding it
# with `nohup ... &` or writing a PID file the way start-dashboard.sh does —
# that pattern exists precisely because a foreground shell session needs to
# hand control back; a launchd agent has no such need and a
# background+PID-file here would just leave launchd babysitting an empty
# shell wrapper instead of the real server.
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

# The wrapper deliberately uses bare `npm` via its exported PATH rather than
# a `$SCRIPT_DIR/../` node target — routine_runner_bin_targets.test.sh
# excludes this wrapper from its node-target check on that basis. Assert the
# wrapper stays that way, so the day it gains a node target, this check
# fails loudly and the exclusion's justification breaks with it.
check "wrapper has no \$SCRIPT_DIR/../ node-target invocation" "yes" \
  "$(! grep -qE '\$SCRIPT_DIR/\.\./' "$WRAPPER" 2>/dev/null && echo yes || echo no)"

# The wrapper's TARGET (the dashboard app it npm-starts) must actually exist
# and be runnable, so a bad path here fails this test instead of failing
# silently at 3am when launchd fires the daemon.
APP_DIR="$REPO_ROOT/skills/dashboard/app"
check "wrapper's app directory exists" "yes" "$([ -d "$APP_DIR" ] && echo yes || echo no)"
check "wrapper's app package.json has a start script" "yes" \
  "$(grep -q '"start"' "$APP_DIR/package.json" 2>/dev/null && echo yes || echo no)"

# The wrapper must self-heal a partial `npm ci` (an interrupted install
# strands a partial node_modules that otherwise never heals) and must
# fail-safe on staleness (missing src dir, or dependency/config files newer
# than the build, not just source files) — no human watches a daemon to
# notice a stale build the way start-dashboard.sh's operator would.
check "wrapper guards npm ci on missing node_modules" "yes" \
  "$(grep -q 'node_modules' "$WRAPPER" 2>/dev/null && echo yes || echo no)"
check "wrapper heals a partial npm ci (checks .package-lock.json)" "yes" \
  "$(grep -q 'node_modules/.package-lock.json' "$WRAPPER" 2>/dev/null && echo yes || echo no)"
check "wrapper checks .next for staleness" "yes" \
  "$(grep -q '\.next' "$WRAPPER" 2>/dev/null && echo yes || echo no)"
check "wrapper's staleness check compares src files against .next" "yes" \
  "$(grep -qE 'find src -newer \.next' "$WRAPPER" 2>/dev/null && echo yes || echo no)"
check "wrapper's staleness check also covers dependency/config files" "yes" \
  "$(grep -qE 'find package\.json package-lock\.json next\.config\.mjs -newer \.next' "$WRAPPER" 2>/dev/null && echo yes || echo no)"

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

# The plist's ProgramArguments path is a machine-specific absolute path (not
# derived from this checkout's location), per install-dashboard-agent.sh's
# own NOTE — that's fine since this machine is the only target. Resolve the
# path's repo-relative suffix against this checkout's own REPO_ROOT (rather
# than asserting the literal absolute path exists) so the guard still works
# from a worktree or another clone, while still catching a wrong or stale
# path baked into the plist.
PLIST_SCRIPT_PATH="$(grep -A2 '<key>ProgramArguments</key>' "$PLIST" | grep -oE '<string>[^<]+</string>' | sed -E 's#</?string>##g' | head -1)"
PLIST_SCRIPT_REL="${PLIST_SCRIPT_PATH#*/skills/dashboard/runner/bin/}"
check "plist's ProgramArguments resolves to the wrapper on disk" "yes" \
  "$([ "$PLIST_SCRIPT_REL" = "dashboard-server.sh" ] && [ -f "$WRAPPER" ] && echo yes || echo no)"

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

# The log dir must be created at a tight mode and then unconditionally
# chmod'd — mkdir -p only sets mode on creation, so a dir left at a looser
# mode by an earlier manual run needs the explicit chmod to be tightened.
check "install script mkdirs the log dir at mode 0700" "yes" \
  "$(grep -qE 'mkdir -p -m 0700' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "install script unconditionally chmod 700s the log dir" "yes" \
  "$(grep -qE 'chmod 700 ' "$INSTALL" 2>/dev/null && echo yes || echo no)"

# A `launchctl bootstrap` from an arbitrary path (the repo dir) only
# survives until logout/reboot — launchd only auto-loads plists that live in
# ~/Library/LaunchAgents/ (the routine-sweeper agents proved this live on
# 2026-07-08: reboot silently unloaded every com.coderails job that had been
# bootstrapped from the repo path). The dashboard installer must copy the
# plist into LaunchAgents and bootstrap FROM THAT COPY, not from
# $SCRIPT_DIR, or the dashboard agent has the same reboot-loss bug.
check "install script references ~/Library/LaunchAgents" "yes" \
  "$(grep -q 'Library/LaunchAgents' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "install script copies the plist with install -m 0644" "yes" \
  "$(grep -qE 'install -m 0644 "\$PLIST" "\$DEST"' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "install script bootstraps from the LaunchAgents copy (DEST), not \$SCRIPT_DIR" "yes" \
  "$(grep -qE 'launchctl bootstrap "\$UID_DOMAIN" "\$DEST"' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "install script does NOT bootstrap directly from \$PLIST (the repo path)" "no" \
  "$(grep -qE 'launchctl bootstrap "\$UID_DOMAIN" "\$PLIST"' "$INSTALL" 2>/dev/null && echo yes || echo no)"
check "uninstall script references ~/Library/LaunchAgents" "yes" \
  "$(grep -q 'Library/LaunchAgents' "$UNINSTALL" 2>/dev/null && echo yes || echo no)"
check "uninstall script removes the LaunchAgents copy (DEST)" "yes" \
  "$(grep -qE 'rm -f "\$DEST"' "$UNINSTALL" 2>/dev/null && echo yes || echo no)"

# The stranded-copy half of the original bug: a refactor that moves the
# `rm -f "$DEST"` above the still-loaded failure check (or above the
# bootout call entirely) would remove the LaunchAgents copy even when the
# job never actually unloaded, defeating the "don't remove while still
# loaded" guarantee the failure branch exists to enforce. Assert the rm
# comes strictly after the failure-check line, not merely that it exists
# somewhere in the file.
check "uninstall script removes DEST only after the still-loaded failure check" "yes" \
  "$(awk '/still loaded after bootout/{err=NR} /rm -f "\$DEST"/{rm=NR} END{print (err && rm && err<rm) ? "yes" : "no"}' "$UNINSTALL")"

# `launchctl bootout` is asynchronous for a running KeepAlive job — it
# returns before the job has actually unloaded (observed live 2026-07-08: a
# running dashboard job unloaded ~2s after bootout returned). A single
# immediate `launchctl print` check right after bootout would spuriously
# report "still loaded" and bail before removing the LaunchAgents copy,
# leaving the plist to auto-load again at next login. The uninstaller must
# actually poll `launchctl print` INSIDE a loop body between bootout and the
# failure declaration, not merely contain a loop keyword somewhere in that
# span (a loop with an empty/no-op body, or an unrelated loop earlier in the
# file, would satisfy a looser check while still having the original bug —
# proven by mutant discrimination in this file's own dev history).
check "uninstall script polls launchctl print inside a loop between bootout and the failure check" "yes" \
  "$(awk '
    /launchctl bootout/ && !bo {bo=NR}
    /for .*in.*seq|while /{if (!loop_start && bo && NR>bo) loop_start=NR}
    loop_start && !loop_done && /^done/ {loop_done=NR}
    /launchctl print/ {if (loop_start && !pr_in_loop && NR>loop_start) pr_in_loop=NR}
    /still loaded after bootout/ && !err {err=NR}
    END{
      ok = (bo && err && loop_start && loop_done && pr_in_loop && bo<loop_start && loop_start<pr_in_loop && pr_in_loop<loop_done && loop_done<err) ? "yes" : "no"
      print ok
    }
  ' "$UNINSTALL")"

if [ "$checks" -eq 0 ]; then
  echo "FAIL - zero checks ran — guard is vacuous"
  exit 1
fi

[ "$fails" -eq 0 ] && { echo "PASS ($checks check(s))"; exit 0; } || { echo "FAILED ($fails/$checks)"; exit 1; }
