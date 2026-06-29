#!/bin/bash
# Behavioural test for scripts/lib/git-common.sh sync logic. Builds a real
# origin + primary-worktree-on-main + linked-worktree-on-feature topology under a
# temp dir and asserts the post-merge sync neither aborts from a worktree nor
# leaves the primary tree's main stale. No network — sync::main_branch is the
# extracted, gh-free core of merge.sh's sync step.
set -u
LIB="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/git-common.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── Topology ───────────────────────────────────────────────────────────────
# origin (bare) ← primary (on main) + linked worktree (on feature). Then origin's
# main advances by one commit, mimicking the just-merged PR.
ORIGIN="$TMP/origin.git"; git init -q --bare "$ORIGIN"
PRIMARY="$TMP/primary"
git clone -q "$ORIGIN" "$PRIMARY"
git -C "$PRIMARY" config user.email t@t.t; git -C "$PRIMARY" config user.name t
git -C "$PRIMARY" commit -q --allow-empty -m init
git -C "$PRIMARY" branch -M main
git -C "$PRIMARY" push -q -u origin main
git -C "$PRIMARY" checkout -q -b feature
git -C "$PRIMARY" commit -q --allow-empty -m "feature work"
git -C "$PRIMARY" push -q -u origin feature
# Linked worktree on the feature branch (this is where the user runs /merge from).
WT="$TMP/wt"
git -C "$PRIMARY" checkout -q main
git -C "$PRIMARY" worktree add -q "$WT" feature
# Simulate the merge having landed on origin/main (advance origin by one commit
# via a throwaway clone, so primary/main is now behind origin/main).
SCRATCH="$TMP/scratch"; git clone -q "$ORIGIN" "$SCRATCH"
git -C "$SCRATCH" config user.email t@t.t; git -C "$SCRATCH" config user.name t
git -C "$SCRATCH" commit -q --allow-empty -m "merged PR #99"
git -C "$SCRATCH" push -q origin main

MERGED_SHA=$(git -C "$SCRATCH" rev-parse HEAD)

# ─── Exercise: run the sync from INSIDE the linked worktree ──────────────────
source "$LIB"
( cd "$WT" && sync::main_branch ) >/dev/null 2>&1
rc=$?

check "sync from a linked worktree exits 0 (does not abort)" 0 "$rc"
check "primary tree's main is fast-forwarded to the merged commit" \
  "$MERGED_SHA" "$(git -C "$PRIMARY" rev-parse main)"

# ─── Regression: the normal path (run from primary, on the feature branch) ───
# Reset: make a second feature + merged commit to re-run the non-worktree path.
git -C "$PRIMARY" worktree remove --force "$WT" 2>/dev/null
git -C "$PRIMARY" checkout -q -b feature2
SCRATCH2="$TMP/scratch2"; git clone -q "$ORIGIN" "$SCRATCH2"
git -C "$SCRATCH2" config user.email t@t.t; git -C "$SCRATCH2" config user.name t
git -C "$SCRATCH2" commit -q --allow-empty -m "merged PR #100"
git -C "$SCRATCH2" push -q origin main
MERGED2=$(git -C "$SCRATCH2" rev-parse HEAD)
( cd "$PRIMARY" && sync::main_branch ) >/dev/null 2>&1
rc2=$?
check "sync from primary tree on a feature branch exits 0" 0 "$rc2"
check "primary tree ends on main, fast-forwarded" "$MERGED2" "$(git -C "$PRIMARY" rev-parse HEAD)"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
