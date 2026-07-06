#!/bin/bash
# Guard test: install.sh's "ARMING SCRIPTS" sweep must be mode-aware — it
# must not fight the git-index-mode invariant that exec_bit_invariant.test.sh
# enforces (PR #94 set scripts/lib/git-common.sh and two other libs to
# 100644 on purpose; a blanket `chmod +x` at install time silently re-arms
# them on disk every time a user runs the installer).
#
# This test copies the real plugin tree to a temp dir, deliberately flips one
# 100644-in-index file to +x on disk (simulating a stale install), one
# 100755-in-index file to -x on disk (simulating a fresh checkout that lost
# its bit), and adds one untracked file with no index entry at all
# (simulating a no-.git release-tarball install), runs install.sh's sweep
# logic against the copy, then asserts: the two tracked files land on their
# index-mandated mode, and the untracked file falls back to the old
# unconditional +x (documented, pre-existing behaviour — not a gap).
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
# Other sourced-only libs under scripts/lib/ that install.sh's literal list
# must also name explicitly — the sweep's only lib glob is
# hooks/scripts/lib/*.sh; there is no scripts/lib/*.sh glob, so anything
# under scripts/lib/ that isn't named literally is silently never swept at all.
OTHER_SOURCE_ONLY_FILES="scripts/lib/review-artifact.sh scripts/lib/config.sh"
# A 100755-in-index file (directly invoked) — sweep must ensure +x on disk.
EXEC_FILE="scripts/push.sh"
# A file NOT in the git index at all (e.g. a release-tarball install with no
# .git) — sweep must fall back to the old unconditional +x. Placed under
# hooks/scripts/lib/, which the sweep globs directly (hooks/scripts/lib/*.sh),
# so it's picked up without needing to be tracked.
UNTRACKED_FILE="hooks/scripts/lib/untracked_scratch.sh"

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
for f in $OTHER_SOURCE_ONLY_FILES; do
  chmod +x "$TMP_TREE/$f"                # stale +x that should be removed
done

# Untracked scratch file — not `git add`ed, so it has no index mode at all
# (simulates a no-.git tarball install where every file takes this path).
printf '#!/bin/bash\ntrue\n' > "$TMP_TREE/$UNTRACKED_FILE"
chmod -x "$TMP_TREE/$UNTRACKED_FILE"

# install.sh also writes unconditionally under $HOME (installed_plugins.json
# scan, ~/.claude/commands conflict scan, settings.json / known_marketplaces.json
# / plugins/marketplaces marketplace registration, ~/.claude/CLAUDE.md append) —
# none of that is redirected by MEMORY_TARGET. Point HOME at a sandbox for the
# duration of the invocation so those writes never touch the developer's real
# home (this previously corrupted a real ~/.claude/settings.json on this
# machine). The sandbox starts empty (freshly mktemp'd, nothing pre-seeded
# except where deliberately noted below) and is never the same path as the
# real HOME captured here before either run.
REAL_HOME="$HOME"
HOME_SANDBOX="$TMP_TREE/.home-sandbox"
mkdir -p "$HOME_SANDBOX"
[ "$HOME_SANDBOX" != "$REAL_HOME" ] || { echo "FAIL - sandbox HOME must differ from real HOME"; exit 1; }

# Pre-seed the sandboxed settings.json and known_marketplaces.json with a
# stale marketplace key so the run below exercises install.sh's real jq
# mutation logic (stage 4: drop stale keys, register coderails, in BOTH
# files) against the sandbox — proving the sandbox isn't merely inert but is
# the actual target of the mutation under test. CLAUDE.md is intentionally
# left absent (its stage-5 append is idempotent-if-present but must also work
# when the file doesn't exist yet — the untouched-vs-created assertion below
# covers that path).
mkdir -p "$HOME_SANDBOX/.claude/plugins"
printf '{"extraKnownMarketplaces":{"workflow-tools":{"source":{"source":"directory","path":"/nonexistent"}}}}\n' \
  > "$HOME_SANDBOX/.claude/settings.json"
printf '{"workflow-tools":{"source":{"source":"directory","path":"/nonexistent"}}}\n' \
  > "$HOME_SANDBOX/.claude/plugins/known_marketplaces.json"

# Seed one conflicting command file so install.sh's conflict-scan prompt
# actually fires (an empty commands dir never triggers the prompt at all,
# so without this the "decline" path below would be silently untested).
# The test's single stdin answer is 'n' (line ~121), so the copy must be
# skipped and the pre-existing file must survive untouched.
mkdir -p "$HOME_SANDBOX/.claude/commands"
printf '# pre-existing user command, must not be overwritten\n' > "$HOME_SANDBOX/.claude/commands/workflow.md"
PRE_EXISTING_WORKFLOW_MD_CKSUM="$(cksum "$HOME_SANDBOX/.claude/commands/workflow.md")"

# Real-HOME files that install.sh writes unconditionally (settings.json,
# known_marketplaces.json, CLAUDE.md) — snapshot all three before the run so
# the leak-proof check below covers every one of them, not just settings.json.
REAL_SETTINGS="$REAL_HOME/.claude/settings.json"
REAL_KNOWN="$REAL_HOME/.claude/plugins/known_marketplaces.json"
REAL_CLAUDE_MD="$REAL_HOME/.claude/CLAUDE.md"
real_settings_cksum_before=""
real_known_cksum_before=""
real_claude_md_cksum_before=""
[ -f "$REAL_SETTINGS" ] && real_settings_cksum_before="$(cksum "$REAL_SETTINGS")"
[ -f "$REAL_KNOWN" ] && real_known_cksum_before="$(cksum "$REAL_KNOWN")"
[ -f "$REAL_CLAUDE_MD" ] && real_claude_md_cksum_before="$(cksum "$REAL_CLAUDE_MD")"

# Run install.sh's sweep in dry mode is not enough (dry-run doesn't chmod) —
# run for real, in the temp copy, non-interactively, then inspect disk modes.
# We invoke the whole script; it only touches files under $PLUGIN_DIR (TMP_TREE)
# and $HOME (now the sandbox above), and needs jq/git on PATH (install.sh makes
# no `gh` calls at all, so no auth/token state under HOME is needed here).
( cd "$TMP_TREE" && printf 'n\n' | HOME="$HOME_SANDBOX" MEMORY_TARGET="$TMP_TREE/.memory-test" bash install.sh >/dev/null 2>&1 )

if [ -n "$real_settings_cksum_before" ]; then
  real_settings_cksum_after="$(cksum "$REAL_SETTINGS")"
  check "real HOME settings.json untouched by sandboxed run (cksum)" "$real_settings_cksum_before" "$real_settings_cksum_after"
fi
if [ -n "$real_known_cksum_before" ]; then
  real_known_cksum_after="$(cksum "$REAL_KNOWN")"
  check "real HOME known_marketplaces.json untouched by sandboxed run (cksum)" "$real_known_cksum_before" "$real_known_cksum_after"
fi
if [ -n "$real_claude_md_cksum_before" ]; then
  real_claude_md_cksum_after="$(cksum "$REAL_CLAUDE_MD")"
  check "real HOME CLAUDE.md untouched by sandboxed run (cksum)" "$real_claude_md_cksum_before" "$real_claude_md_cksum_after"
else
  check "real HOME CLAUDE.md still absent after sandboxed run (no leak-created file)" "no" "$([ -f "$REAL_CLAUDE_MD" ] && echo yes || echo no)"
fi

check "sandboxed settings.json drops stale workflow-tools key (real jq mutation exercised)" \
  "null" "$(jq -r '.extraKnownMarketplaces["workflow-tools"] // "null"' "$HOME_SANDBOX/.claude/settings.json" 2>/dev/null)"
check "sandboxed settings.json registers coderails marketplace pointing at the sandbox tree" \
  "$TMP_TREE" "$(jq -r '.extraKnownMarketplaces.coderails.source.path // "null"' "$HOME_SANDBOX/.claude/settings.json" 2>/dev/null)"
check "sandboxed known_marketplaces.json drops stale workflow-tools key (real jq mutation exercised)" \
  "null" "$(jq -r '.["workflow-tools"] // "null"' "$HOME_SANDBOX/.claude/plugins/known_marketplaces.json" 2>/dev/null)"
check "sandboxed CLAUDE.md gains the Self-Checking Discipline section (real append exercised)" \
  "yes" "$(grep -q '## Self-Checking Discipline' "$HOME_SANDBOX/.claude/CLAUDE.md" 2>/dev/null && echo yes || echo no)"

check "commands dir conflict declined: pre-existing workflow.md is unchanged (cksum)" \
  "$PRE_EXISTING_WORKFLOW_MD_CKSUM" "$(cksum "$HOME_SANDBOX/.claude/commands/workflow.md" 2>/dev/null)"
check "commands dir conflict declined: no other command file was copied in" \
  "1" "$(find "$HOME_SANDBOX/.claude/commands" -type f | wc -l | tr -d ' ')"

is_executable() { [ -x "$1" ] && echo yes || echo no; }

# Index mode is read from the REAL repo (the temp copy isn't a git repo / doesn't
# carry index metadata) — this mirrors what install.sh itself must do: shell out
# to `git ls-files -s` from the plugin dir to learn the intended mode per file.
index_mode_source_only=$(git -C "$REPO_ROOT" ls-files -s -- "$SOURCE_ONLY_FILE" | awk '{print $1}')
index_mode_exec=$(git -C "$REPO_ROOT" ls-files -s -- "$EXEC_FILE" | awk '{print $1}')

check "$SOURCE_ONLY_FILE index mode is 100644 (precondition)" "100644" "$index_mode_source_only"
check "$EXEC_FILE index mode is 100755 (precondition)" "100755" "$index_mode_exec"
for f in $OTHER_SOURCE_ONLY_FILES; do
  index_mode_other=$(git -C "$REPO_ROOT" ls-files -s -- "$f" | awk '{print $1}')
  check "$f index mode is 100644 (precondition)" "100644" "$index_mode_other"
done

check "$SOURCE_ONLY_FILE loses stale +x after sweep (100644-in-index)" "no" "$(is_executable "$TMP_TREE/$SOURCE_ONLY_FILE")"
check "$EXEC_FILE gains +x after sweep (100755-in-index)" "yes" "$(is_executable "$TMP_TREE/$EXEC_FILE")"
check "$UNTRACKED_FILE gains +x after sweep (not in index, fallback behaviour)" "yes" "$(is_executable "$TMP_TREE/$UNTRACKED_FILE")"
for f in $OTHER_SOURCE_ONLY_FILES; do
  check "$f loses stale +x after sweep (100644-in-index, must be named in install.sh's literal list)" "no" "$(is_executable "$TMP_TREE/$f")"
done

# --- No-git-checkout case (release tarball, no .git anywhere) ---
# `git ls-files -s` exits 128 outside a git repo/worktree. Under install.sh's
# `set -euo pipefail`, that non-zero exit propagates through the sweep's pipe
# and (without a guard) kills the whole installer at the very first swept
# file — everything after the sweep (marketplace registration etc.) silently
# never runs. This must be caught: the sweep should complete and every file
# should fall back to the old unconditional +x.
NOGIT_TREE="$(mktemp -d)"
cleanup_nogit() { rm -rf "$NOGIT_TREE"; }
trap 'cleanup; cleanup_nogit' EXIT

cp -r "$TMP_TREE/." "$NOGIT_TREE/"
rm -rf "$NOGIT_TREE/.git"   # `git worktree add` leaves a `.git` file pointing at the main repo — remove it entirely

# Reset the tracked files to their pre-sweep drift state again (the copy above
# picked up the already-corrected TMP_TREE) so this run exercises the sweep
# fresh, independent of the first run.
chmod +x "$NOGIT_TREE/$SOURCE_ONLY_FILE"
chmod -x "$NOGIT_TREE/$EXEC_FILE"
for f in $OTHER_SOURCE_ONLY_FILES; do
  chmod +x "$NOGIT_TREE/$f"
done

NOGIT_HOME_SANDBOX="$NOGIT_TREE/.home-sandbox"
mkdir -p "$NOGIT_HOME_SANDBOX"

# Pre-seed with the same stale marketplace key as the tracked run's sandbox
# (lines 97-101 above) so this run also exercises install.sh's real jq
# mutation logic in the no-git path, not just an inert empty sandbox —
# mirrors the tracked-run's anti-vacuity technique.
mkdir -p "$NOGIT_HOME_SANDBOX/.claude/plugins"
printf '{"extraKnownMarketplaces":{"workflow-tools":{"source":{"source":"directory","path":"/nonexistent"}}}}\n' \
  > "$NOGIT_HOME_SANDBOX/.claude/settings.json"
printf '{"workflow-tools":{"source":{"source":"directory","path":"/nonexistent"}}}\n' \
  > "$NOGIT_HOME_SANDBOX/.claude/plugins/known_marketplaces.json"

nogit_exit=0
( cd "$NOGIT_TREE" && printf 'n\n' | HOME="$NOGIT_HOME_SANDBOX" MEMORY_TARGET="$NOGIT_TREE/.memory-test" bash install.sh >/dev/null 2>&1 ) || nogit_exit=$?

if [ -n "$real_settings_cksum_before" ]; then
  real_settings_cksum_after_nogit="$(cksum "$REAL_SETTINGS")"
  check "real HOME settings.json still untouched after no-git sandboxed run (cksum)" "$real_settings_cksum_before" "$real_settings_cksum_after_nogit"
fi
if [ -n "$real_known_cksum_before" ]; then
  real_known_cksum_after_nogit="$(cksum "$REAL_KNOWN")"
  check "real HOME known_marketplaces.json still untouched after no-git sandboxed run (cksum)" "$real_known_cksum_before" "$real_known_cksum_after_nogit"
fi
if [ -n "$real_claude_md_cksum_before" ]; then
  real_claude_md_cksum_after_nogit="$(cksum "$REAL_CLAUDE_MD")"
  check "real HOME CLAUDE.md still untouched after no-git sandboxed run (cksum)" "$real_claude_md_cksum_before" "$real_claude_md_cksum_after_nogit"
else
  check "real HOME CLAUDE.md still absent after no-git sandboxed run (no leak-created file)" "no" "$([ -f "$REAL_CLAUDE_MD" ] && echo yes || echo no)"
fi
check "no-git sandboxed CLAUDE.md gains the Self-Checking Discipline section (real append exercised)" \
  "yes" "$(grep -q '## Self-Checking Discipline' "$NOGIT_HOME_SANDBOX/.claude/CLAUDE.md" 2>/dev/null && echo yes || echo no)"

check "no-git sandboxed settings.json drops stale workflow-tools key (real jq mutation exercised)" \
  "null" "$(jq -r '.extraKnownMarketplaces["workflow-tools"] // "null"' "$NOGIT_HOME_SANDBOX/.claude/settings.json" 2>/dev/null)"
check "no-git sandboxed settings.json registers coderails marketplace pointing at the nogit tree" \
  "$NOGIT_TREE" "$(jq -r '.extraKnownMarketplaces.coderails.source.path // "null"' "$NOGIT_HOME_SANDBOX/.claude/settings.json" 2>/dev/null)"
check "no-git sandboxed known_marketplaces.json drops stale workflow-tools key (real jq mutation exercised)" \
  "null" "$(jq -r '.["workflow-tools"] // "null"' "$NOGIT_HOME_SANDBOX/.claude/plugins/known_marketplaces.json" 2>/dev/null)"

check "install.sh exits 0 in a no-git checkout (does not die mid-sweep)" "0" "$nogit_exit"
check "$SOURCE_ONLY_FILE gains +x in a no-git checkout (fallback applied to every file)" "yes" "$(is_executable "$NOGIT_TREE/$SOURCE_ONLY_FILE")"
for f in $OTHER_SOURCE_ONLY_FILES; do
  check "$f gains +x in a no-git checkout (fallback applied to every file)" "yes" "$(is_executable "$NOGIT_TREE/$f")"
done

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
