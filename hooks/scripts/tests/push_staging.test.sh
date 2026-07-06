#!/bin/bash
# Behavioural test for scripts/push.sh staging behaviour. Builds a real
# bare origin + clone fixture per case (matching git-common.test.sh's
# convention) and runs push.sh as a real subprocess (`bash "$PUSH_SH"`, not
# `source`d — push.sh resolves its sibling lib via `$(dirname "$0")`, which
# only points at push.sh's own directory when it's actually executed, not
# sourced into a caller with a different $0). `git add -A` was replaced with
# `git add -u` (tracked-only staging) plus an untracked-file warning. No
# network — each fixture's origin remote is a nonexistent github.com URL so
# require::repo() passes, but the subsequent `git push` inside push.sh fails
# fast (no such repo) and push.sh's `set -euo pipefail` aborts it right after
# the commit step under test, before any `gh pr` call is reached.
set -u
export GIT_TERMINAL_PROMPT=0
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PUSH_SH="$REPO_ROOT/scripts/push.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# new_fixture <name> → sets up $TMP/<name>/origin.git (bare) + $TMP/<name>/repo
# (clone, on a feature branch, remote-HEAD set to main) and echoes the repo path.
# push.sh's require::repo() gates on repo() matching a github.com URL, so
# `origin` is registered as a fake https://github.com/... URL purely so
# repo()/require::repo() pass — this repo is never actually reachable. The
# `main` branch is a LOCAL branch only (never pushed anywhere), so `origin/main`
# (used by ahead()/dirty-independent bits) resolves via a local remote-tracking
# ref we set up manually, and the subsequent `git push -u origin "$br"` inside
# push::main fails fast (no such host reachable / not a real remote) — this
# happens AFTER the commit step under test, and `set -euo pipefail` inside
# push.sh then aborts the subshell right there, so push.sh's later `gh pr`
# calls (which would otherwise hit the real network) are never reached.
new_fixture() {
  local name="$1" origin repo
  origin="$TMP/$name/origin.git"; repo="$TMP/$name/repo"
  mkdir -p "$TMP/$name"
  git init -q --bare "$origin"
  git clone -q "$origin" "$repo" 2>/dev/null
  git -C "$repo" config user.email t@t.t; git -C "$repo" config user.name t
  echo "base" > "$repo/base.txt"
  git -C "$repo" add base.txt
  git -C "$repo" commit -q -m init
  git -C "$repo" branch -M main
  git -C "$repo" push -q -u origin main
  git -C "$repo" remote set-head origin main
  git -C "$repo" remote set-url origin "https://github.com/testowner/testrepo-does-not-exist-coderails-test.git"
  git -C "$repo" checkout -q -b feature
  echo "$repo"
}

# ─── TRACKED-ONLY: modified tracked file, no untracked files ────────────────
# No `??` lines exist here at all, which is the common case and the one that
# previously crashed push.sh (a bare `grep '^??'` with zero matches exits 1,
# and under `set -euo pipefail` that aborted the whole script before the
# commit ever ran) — assert on exit code and HEAD advancing, not just content,
# so a future regression that skips the commit can't pass silently.
R=$(new_fixture tracked_only)
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "changed" > "$R/base.txt"
OUT=$( ( cd "$R" && bash "$PUSH_SH" ) 2>&1 )
RC=$?
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
staged=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "TRACKED-ONLY: does not crash (exit 0)" "0" "$RC"
check "TRACKED-ONLY: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "TRACKED-ONLY: modification staged and committed" "base.txt" "$staged"
check "TRACKED-ONLY: no untracked-file warning printed" "0" "$(printf '%s' "$OUT" | grep -c -i 'untracked')"

# ─── UNTRACKED-PRESENT: modified tracked file AND an untracked file ─────────
R=$(new_fixture untracked_present)
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
echo "changed" > "$R/base.txt"
echo "new" > "$R/newfile.txt"
OUT=$( ( cd "$R" && bash "$PUSH_SH" ) 2>&1 )
RC=$?
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
committed_files=$(git -C "$R" show --name-only -1 --format="" HEAD 2>/dev/null)
check "UNTRACKED-PRESENT: does not crash (exit 0)" "0" "$RC"
check "UNTRACKED-PRESENT: HEAD advances (a new commit was made)" "1" "$([ "$BEFORE_HEAD" != "$AFTER_HEAD" ] && echo 1 || echo 0)"
check "UNTRACKED-PRESENT: modification staged and committed" "base.txt" "$committed_files"
check "UNTRACKED-PRESENT: untracked file NOT staged" "0" "$(printf '%s' "$committed_files" | grep -c newfile.txt)"
check "UNTRACKED-PRESENT: warning printed" "1" "$(printf '%s' "$OUT" | grep -c -i 'untracked')"
check "UNTRACKED-PRESENT: warning names the file" "1" "$(printf '%s' "$OUT" | grep -c 'newfile.txt')"
check "UNTRACKED-PRESENT: warning mentions git add" "1" "$(printf '%s' "$OUT" | grep -c -i 'git add')"

# ─── UNTRACKED-ONLY: no tracked changes at all, only a new untracked file ───
R=$(new_fixture untracked_only)
echo "new" > "$R/newfile.txt"
BEFORE_HEAD=$(git -C "$R" rev-parse HEAD)
OUT=$( ( cd "$R" && bash "$PUSH_SH" ) 2>&1 )
RC=$?
AFTER_HEAD=$(git -C "$R" rev-parse HEAD)
check "UNTRACKED-ONLY: does not crash (exit 0)" "0" "$RC"
check "UNTRACKED-ONLY: no new commit created (nothing staged)" "$BEFORE_HEAD" "$AFTER_HEAD"
check "UNTRACKED-ONLY: warning still printed" "1" "$(printf '%s' "$OUT" | grep -c -i 'untracked')"

# ─── MULTIPLE UNTRACKED: warning lists all untracked files ──────────────────
R=$(new_fixture multi_untracked)
echo "changed" > "$R/base.txt"
echo "a" > "$R/alpha.txt"
echo "b" > "$R/beta.txt"
OUT=$( ( cd "$R" && bash "$PUSH_SH" ) 2>&1 )
RC=$?
check "MULTIPLE UNTRACKED: does not crash (exit 0)" "0" "$RC"
check "MULTIPLE UNTRACKED: alpha.txt named in warning" "1" "$(printf '%s' "$OUT" | grep -c 'alpha.txt')"
check "MULTIPLE UNTRACKED: beta.txt named in warning" "1" "$(printf '%s' "$OUT" | grep -c 'beta.txt')"

# ─── NEGATIVE CONTROL: script no longer contains git add -A ─────────────────
check "NEGATIVE CONTROL: push.sh contains zero 'git add -A'" "0" "$(grep -c 'git add -A' "$PUSH_SH")"
check "NEGATIVE CONTROL: push.sh contains 'git add -u'" "1" "$(grep -c 'git add -u' "$PUSH_SH" | head -1)"

printf '\n--- push_staging.test.sh: %d failing checks ---\n' "$fails"
[ "$fails" -eq 0 ] && exit 0 || exit 1
