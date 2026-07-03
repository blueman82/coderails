#!/bin/bash
# Guard test: install.sh's "ARMING SCRIPTS" sweep must be mode-aware — it
# must not fight the git-index-mode invariant that exec_bit_invariant.test.sh
# enforces (PR #94 set scripts/lib/git-common.sh and two other libs to
# 100644 on purpose; a blanket `chmod +x` at install time silently re-arms
# them on disk every time a user runs the installer).
#
# This test copies the real plugin tree to a temp dir, deliberately flips one
# 100644-in-index file to +x on disk (simulating a stale install) and one
# 100755-in-index file to -x on disk (simulating a fresh checkout that lost
# its bit), runs install.sh's sweep logic against the copy, then asserts the
# disk mode was corrected to match the git index mode in both directions.
#
# Uses parallel arrays, not `declare -A`, for bash 3.2 (macOS default) compat
# — same constraint the other *.test.sh files in this directory respect.
#
# Usage: bash install_mode_sweep.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

fails=0
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s (%s)\n' "$1" "$2"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# A 100644-in-index file (sourced-only lib) — sweep must ensure -x on disk.
SOURCE_ONLY_FILE="scripts/lib/git-common.sh"
# A 100755-in-index file (directly invoked) — sweep must ensure +x on disk.
EXEC_FILE="scripts/push.sh"

TMP_TREE="$(mktemp -d)"
cleanup() {
  git -C "$REPO_ROOT" worktree remove --force "$TMP_TREE" >/dev/null 2>&1
  rm -rf "$TMP_TREE"
}
trap cleanup EXIT

# A real `git worktree` (not a bare file copy) so `git ls-files -s` inside the
# temp tree sees the same index modes as the real repo — install.sh's sweep
# must be able to shell out to `git ls-files -s` from the plugin dir. Checked
# out from HEAD, then the working tree's install.sh (which may carry
# uncommitted edits under test) is overlaid on top.
rm -rf "$TMP_TREE"
git -C "$REPO_ROOT" worktree add --detach -f "$TMP_TREE" HEAD >/dev/null 2>&1
cp "$REPO_ROOT/install.sh" "$TMP_TREE/install.sh"

# Simulate drift in both directions before running the sweep.
chmod +x "$TMP_TREE/$SOURCE_ONLY_FILE"   # stale +x that should be removed
chmod -x "$TMP_TREE/$EXEC_FILE"          # missing +x that should be added

# Run install.sh's sweep in dry mode is not enough (dry-run doesn't chmod) —
# run for real, in the temp copy, non-interactively, then inspect disk modes.
# We invoke the whole script; it only touches files under $PLUGIN_DIR (TMP_TREE),
# and needs gh/jq/git on PATH (present — same prerequisites as the real installer).
( cd "$TMP_TREE" && printf 'n\n' | MEMORY_TARGET="$TMP_TREE/.memory-test" bash install.sh >/dev/null 2>&1 )

is_executable() { [ -x "$1" ] && echo yes || echo no; }

# Index mode is read from the REAL repo (the temp copy isn't a git repo / doesn't
# carry index metadata) — this mirrors what install.sh itself must do: shell out
# to `git ls-files -s` from the plugin dir to learn the intended mode per file.
index_mode_source_only=$(git -C "$REPO_ROOT" ls-files -s -- "$SOURCE_ONLY_FILE" | awk '{print $1}')
index_mode_exec=$(git -C "$REPO_ROOT" ls-files -s -- "$EXEC_FILE" | awk '{print $1}')

check "$SOURCE_ONLY_FILE index mode is 100644 (precondition)" "100644" "$index_mode_source_only"
check "$EXEC_FILE index mode is 100755 (precondition)" "100755" "$index_mode_exec"

check "$SOURCE_ONLY_FILE loses stale +x after sweep (100644-in-index)" "no" "$(is_executable "$TMP_TREE/$SOURCE_ONLY_FILE")"
check "$EXEC_FILE gains +x after sweep (100755-in-index)" "yes" "$(is_executable "$TMP_TREE/$EXEC_FILE")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
