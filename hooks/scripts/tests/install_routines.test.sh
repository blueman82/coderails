#!/bin/bash
# Guard test: launchd/install-routines.sh must install the routine-sweeper
# plists so they survive a reboot. A `launchctl bootstrap` from an arbitrary
# path (the repo directory) only lasts until logout/reboot — launchd only
# auto-loads plists that live in ~/Library/LaunchAgents/. The first live fire
# of the routines system (2026-07-08) proved this: the 03:00 run succeeded,
# the machine rebooted at 07:34, and afterwards `launchctl list` showed NO
# com.coderails jobs and ~/Library/LaunchAgents/ held NO com.coderails plists
# — the whole routines system had silently unloaded.
#
# The fix: install copies each plist to ~/Library/LaunchAgents/<label>.plist
# and bootstraps from THAT copy (not the repo path); uninstall boots out the
# label and removes the copy. This test drives both scripts against a mktemp
# fake HOME with a stubbed `launchctl` on PATH that records its invocations to
# a file, so the real launchd/gui domain and real ~/Library/LaunchAgents are
# never touched. It asserts: install copies both plists into the fake
# LaunchAgents dir with the right names, bootstraps from the LaunchAgents path
# (not the repo path), and is idempotent; uninstall boots out both labels,
# removes both copies, and is idempotent (including when nothing is installed).
#
# bash 3.2 (macOS default) compatible — no `declare -A`, same constraint the
# other *.test.sh files in this directory respect.
#
# Usage: bash install_routines.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LAUNCHD_DIR="$REPO_ROOT/launchd"

fails=0
checks=0
check() { # desc expected actual
  checks=$((checks+1))
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

LABELS="com.coderails.routine-sweeper.calendar com.coderails.routine-sweeper.watch"

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

FAKE_HOME="$TMP/home"
BIN_STUB="$TMP/bin"
LAUNCHCTL_LOG="$TMP/launchctl.log"
mkdir -p "$FAKE_HOME" "$BIN_STUB"

# Stub launchctl: record every invocation (one line of args per call) and
# succeed. `bootout` must succeed here — the real script relies on `|| true`
# to ignore not-found, but a plain success is fine for recording intent.
cat > "$BIN_STUB/launchctl" <<STUB
#!/bin/bash
printf '%s\n' "\$*" >> "$LAUNCHCTL_LOG"
exit 0
STUB
chmod +x "$BIN_STUB/launchctl"

LA_DIR="$FAKE_HOME/Library/LaunchAgents"

run_install() {
  ( cd "$LAUNCHD_DIR" && HOME="$FAKE_HOME" PATH="$BIN_STUB:$PATH" \
      bash "$LAUNCHD_DIR/install-routines.sh" >/dev/null 2>&1 )
}
run_uninstall() {
  ( cd "$LAUNCHD_DIR" && HOME="$FAKE_HOME" PATH="$BIN_STUB:$PATH" \
      bash "$LAUNCHD_DIR/uninstall-routines.sh" >/dev/null 2>&1 )
}

# --- Install ---
: > "$LAUNCHCTL_LOG"
run_install
install_rc=$?
check "install exits 0" "0" "$install_rc"

for label in $LABELS; do
  check "install copies $label.plist into ~/Library/LaunchAgents" \
    "yes" "$([ -f "$LA_DIR/$label.plist" ] && echo yes || echo no)"
  # The copy must be byte-identical to the repo source.
  check "$label.plist copy matches repo source (cksum)" \
    "$(cksum "$LAUNCHD_DIR/$label.plist" | awk '{print $1}')" \
    "$(cksum "$LA_DIR/$label.plist" 2>/dev/null | awk '{print $1}')"
  # Bootstrap must reference the LaunchAgents copy, NOT the repo path — this
  # is the whole point of the fix.
  check "install bootstraps $label from the LaunchAgents copy" \
    "yes" "$(grep -q "bootstrap .*$LA_DIR/$label.plist" "$LAUNCHCTL_LOG" && echo yes || echo no)"
  check "install does NOT bootstrap $label from the repo path" \
    "no" "$(grep -q "bootstrap .*$LAUNCHD_DIR/$label.plist" "$LAUNCHCTL_LOG" && echo yes || echo no)"
done

# Log dir created 0700 (pre-existing behaviour, must survive the change).
check "routines log dir created" \
  "yes" "$([ -d "$FAKE_HOME/.claude/coderails-dashboard/routines" ] && echo yes || echo no)"
check "routines log dir is 0700" \
  "700" "$(stat -f '%Lp' "$FAKE_HOME/.claude/coderails-dashboard/routines" 2>/dev/null)"

# --- Install idempotency ---
run_install
install_rc2=$?
check "second install exits 0 (idempotent)" "0" "$install_rc2"
for label in $LABELS; do
  check "$label.plist still present after second install" \
    "yes" "$([ -f "$LA_DIR/$label.plist" ] && echo yes || echo no)"
done
plist_count="$(find "$LA_DIR" -maxdepth 1 -name 'com.coderails.routine-sweeper.*.plist' -type f | wc -l | tr -d ' ')"
check "exactly 2 coderails plists in LaunchAgents (no duplicates)" "2" "$plist_count"

# --- Uninstall ---
: > "$LAUNCHCTL_LOG"
run_uninstall
uninstall_rc=$?
check "uninstall exits 0" "0" "$uninstall_rc"
for label in $LABELS; do
  check "uninstall removes $label.plist from ~/Library/LaunchAgents" \
    "yes" "$([ ! -f "$LA_DIR/$label.plist" ] && echo yes || echo no)"
  check "uninstall boots out $label" \
    "yes" "$(grep -q "bootout .*$label" "$LAUNCHCTL_LOG" && echo yes || echo no)"
done

# --- Uninstall idempotency (nothing installed) ---
run_uninstall
uninstall_rc2=$?
check "second uninstall exits 0 (idempotent, nothing to remove)" "0" "$uninstall_rc2"

# --- Uninstall of an old-style install (repo-path bootstrap, no copy) ---
# Simulate the pre-fix state: labels were bootstrapped from the repo path and
# no LaunchAgents copy exists. Uninstall must still boot out by label and not
# error on the missing copy.
: > "$LAUNCHCTL_LOG"
rm -f "$LA_DIR"/com.coderails.routine-sweeper.*.plist 2>/dev/null
run_uninstall
uninstall_rc3=$?
check "uninstall exits 0 against an old-style install (no copy present)" "0" "$uninstall_rc3"
for label in $LABELS; do
  check "uninstall still boots out $label when no copy exists" \
    "yes" "$(grep -q "bootout .*$label" "$LAUNCHCTL_LOG" && echo yes || echo no)"
done

# --- Empty-glob guard ---
# Copy each script into a launchd dir that has NO plists at all. Under
# `set -euo pipefail` an unguarded glob would expand to the literal pattern
# and crash mid-loop with a cryptic error; the nullglob + guard must instead
# exit non-zero with a clear "no plists found" message and touch nothing.
EMPTY_LAUNCHD="$TMP/empty-launchd"
EMPTY_HOME="$TMP/empty-home"
mkdir -p "$EMPTY_LAUNCHD" "$EMPTY_HOME"
cp "$LAUNCHD_DIR/install-routines.sh" "$LAUNCHD_DIR/uninstall-routines.sh" "$EMPTY_LAUNCHD/"

empty_install_out="$( cd "$EMPTY_LAUNCHD" && HOME="$EMPTY_HOME" PATH="$BIN_STUB:$PATH" \
    bash "$EMPTY_LAUNCHD/install-routines.sh" 2>&1 )"
empty_install_rc=$?
check "install exits non-zero when no plists present" \
  "yes" "$([ "$empty_install_rc" -ne 0 ] && echo yes || echo no)"
check "install prints a clear no-plists error" \
  "yes" "$(printf '%s' "$empty_install_out" | grep -q 'no com.coderails.routine-sweeper' && echo yes || echo no)"

empty_uninstall_out="$( cd "$EMPTY_LAUNCHD" && HOME="$EMPTY_HOME" PATH="$BIN_STUB:$PATH" \
    bash "$EMPTY_LAUNCHD/uninstall-routines.sh" 2>&1 )"
empty_uninstall_rc=$?
check "uninstall exits non-zero when no plists present" \
  "yes" "$([ "$empty_uninstall_rc" -ne 0 ] && echo yes || echo no)"

if [ "$checks" -eq 0 ]; then
  echo "FAIL - zero checks ran — guard is vacuous"
  exit 1
fi

[ "$fails" -eq 0 ] && { echo "PASS ($checks checks)"; exit 0; } || { echo "FAILED ($fails/$checks)"; exit 1; }
