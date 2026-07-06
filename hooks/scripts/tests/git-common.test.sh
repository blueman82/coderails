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
# Set origin/HEAD so main() (git symbolic-ref refs/remotes/origin/HEAD) resolves —
# this is the state a real `gh`/`git clone` leaves behind; a bare `git init` origin
# does not have it, which would make main() empty and the sync a no-op.
git -C "$PRIMARY" remote set-head origin main
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

# ─── Finding 1: a primary-tree path containing a SPACE must not be truncated ──
# Build a fresh origin + primary-with-a-space + linked worktree, then sync from
# the worktree. A naive `awk '{print $2}'` truncates the path at the space and
# the `git -C <truncated>` fails → main never advances.
SP="$TMP/has space"; mkdir -p "$SP"
ORIGIN3="$TMP/o3.git"; git init -q --bare "$ORIGIN3"
PRIMARY3="$SP/primary"; git clone -q "$ORIGIN3" "$PRIMARY3"
git -C "$PRIMARY3" config user.email t@t.t; git -C "$PRIMARY3" config user.name t
git -C "$PRIMARY3" commit -q --allow-empty -m init; git -C "$PRIMARY3" branch -M main
git -C "$PRIMARY3" push -q -u origin main
git -C "$PRIMARY3" remote set-head origin main
git -C "$PRIMARY3" checkout -q -b feature3; git -C "$PRIMARY3" commit -q --allow-empty -m work
git -C "$PRIMARY3" checkout -q main
WT3="$SP/wt3"; git -C "$PRIMARY3" worktree add -q "$WT3" feature3
SC3="$TMP/sc3"; git clone -q "$ORIGIN3" "$SC3"
git -C "$SC3" config user.email t@t.t; git -C "$SC3" config user.name t
git -C "$SC3" commit -q --allow-empty -m "merged"; git -C "$SC3" push -q origin main
MERGED3=$(git -C "$SC3" rev-parse HEAD)
( cd "$WT3" && sync::main_branch ) >/dev/null 2>&1
check "worktree whose primary path has a space -> main still synced" \
  "$MERGED3" "$(git -C "$PRIMARY3" rev-parse main)"

# ─── Finding 2: under `set -e` (merge.sh's context), a failing sync must NOT ──
# abort the caller. Simulate an unreachable origin so the pull fails, and assert
# the surrounding `set -e` script keeps running to its sentinel.
git -C "$PRIMARY" remote set-url origin "$TMP/does-not-exist.git"
git -C "$PRIMARY" checkout -q -b feature4
survived=$( set -e; ( cd "$PRIMARY" && sync::main_branch ) >/dev/null 2>&1; echo SURVIVED )
check "failing sync under set -e does not abort the caller" SURVIVED "$survived"

# ─── main() fallback: no origin/HEAD marker must fall back to "main" ──────────
# A bare `git init` repo has no `refs/remotes/origin/HEAD`, so `git symbolic-ref`
# fails. The `|| echo main` fallback must then fire. The bug: the `|| ` bound to
# the whole pipeline, whose exit status is sed's (0 on empty input), so the
# fallback never fired and main() returned a blank.
NOMARK="$TMP/nomark"; git init -q "$NOMARK"
git -C "$NOMARK" config user.email t@t.t; git -C "$NOMARK" config user.name t
git -C "$NOMARK" commit -q --allow-empty -m init
check "main() falls back to 'main' when origin/HEAD is unset" \
  "main" "$( cd "$NOMARK" && main )"

# ─── pr::head_sha + pr::has_coderails_review_for_head ───────────────────────
# These helpers call `gh`. Stub it via a PATH-injected fake script.
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR"

ARTIFACT_LIB="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/review-artifact.sh"
source "$ARTIFACT_LIB"

GOOD_MARKER=$(review_artifact::marker 42 "deadbeef")
OTHER_SHA_MARKER=$(review_artifact::marker 42 "othershaX")
V2_MARKER="<!-- coderails-review-summary v2 pr=42 head_sha=deadbeef -->"

# Helper: write a gh stub and source git-common.sh fresh so it picks up the stub
run_with_stub() {
    local stub_body="$1"; shift
    local stub="$STUB_DIR/gh"
    printf '#!/bin/bash\n%s\n' "$stub_body" > "$stub"
    chmod +x "$stub"
    # Source git-common.sh in a subshell with the stub dir prepended to PATH
    (
        export PATH="$STUB_DIR:$PATH"
        source "$LIB"
        "$@"
    )
}

# Stub: pr view headRefOid → returns "deadbeef"
HEAD_SHA_STUB='echo "deadbeef"'
result=$(run_with_stub "$HEAD_SHA_STUB" pr::head_sha 42)
check "pr::head_sha: returns sha from gh output" "deadbeef" "$result"

# Stub: gh fails (non-zero exit) → pr::head_sha returns empty
FAIL_STUB='exit 1'
result=$(run_with_stub "$FAIL_STUB" pr::head_sha 42)
check "pr::head_sha: gh failure → empty result" "" "$result"

# ─── Trusted-author gh stub builder ──────────────────────────────────────────
# Both gate readers now call `gh` twice: `gh api user -q .login` (identity,
# once per process) and the paginated REST comments fetch
# `gh api repos/{owner}/{repo}/issues/{n}/comments --paginate --jq '...'`.
# comment_row() builds one raw JSON comment object; gh_stub_rows() builds a
# stub `gh` script that branches on "$@": returns TRUSTED_LOGIN for `api user`,
# and re-implements the same jq selection the real code runs (select on
# login==trusted and author_association==OWNER, emit body as base64) directly
# in the stub, over the JSON array passed in — this mirrors production without
# needing a live GitHub server.
TRUSTED_LOGIN="trusted-bot"

# comment_row <login> <assoc> <body>
# Echoes one JSON object for the comments array (body is JSON-string-escaped
# via jq -Rs so embedded newlines/quotes in a marker+prose body are safe).
comment_row() {
    local login="$1" assoc="$2" body="$3"
    local body_json; body_json=$(printf '%s' "$body" | jq -Rs .)
    printf '{"user":{"login":"%s"},"author_association":"%s","body":%s}' "$login" "$assoc" "$body_json"
}

# gh_stub_rows <rows_json_array>
# Builds a gh stub body (to hand to run_with_stub) that serves TRUSTED_LOGIN
# for identity and the given JSON array of comment rows for the comments
# fetch, applying the SAME trusted-author filter the production code applies
# (so these tests exercise the filter's actual jq expression, not a re-guess
# of it) — the filter logic itself still lives only in git-common.sh; this
# helper composes the fixture, it does not duplicate the security decision.
gh_stub_rows() {
    local rows="$1"
    cat <<STUB
case "\$*" in
  "api user -q .login")
    echo "$TRUSTED_LOGIN"
    ;;
  *"issues/42/comments --paginate"*)
    printf '%s' '$rows' | jq -c '.[] | select(.user.login == "$TRUSTED_LOGIN" and .author_association == "OWNER") | (.body | @base64)' -r
    ;;
  *)
    exit 1
    ;;
esac
STUB
}

# gh_stub_identity_fail
# Identity fetch itself fails (gh api user exits non-zero) — comments call
# never has a chance to run.
IDENTITY_FAIL_STUB='case "$*" in
  "api user -q .login") exit 1 ;;
  *) exit 1 ;;
esac'

# gh_stub_comments_fail
# Identity succeeds but the comments fetch fails.
COMMENTS_FAIL_STUB="case \"\$*\" in
  \"api user -q .login\") echo \"$TRUSTED_LOGIN\" ;;
  *\"issues/42/comments --paginate\"*) exit 1 ;;
  *) exit 1 ;;
esac"

# E1 negative control / trust baseline: trusted OWNER posts a valid marker → exit 0
ROWS_TRUSTED_MATCH=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_MATCH")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: trusted OWNER matching marker → exit 0" 0 $?

# E1: untrusted login posts a byte-identical valid marker → exit 1 (spoofing rejected)
ROWS_SPOOF=$(printf '[%s]' "$(comment_row "attacker" CONTRIBUTOR "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_SPOOF")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: untrusted login byte-identical marker → exit 1 (spoof rejected)" 1 $?

# E1: trusted login but NOT OWNER association → exit 1 (association also enforced)
ROWS_TRUSTED_NOT_OWNER=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" CONTRIBUTOR "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_NOT_OWNER")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: trusted login, non-OWNER association → exit 1" 1 $?

# Stub: comment body contains a marker for a different SHA → exit 1 (no match)
ROWS_WRONG_SHA=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$OTHER_SHA_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_WRONG_SHA")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: different sha marker → exit 1" 1 $?

# Stub: comment body contains a v2 marker → exit 1 (fail-closed on unknown version)
ROWS_V2=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$V2_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_V2")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: v2 marker → exit 1 (fail-closed)" 1 $?

# Stub: no comments (empty array) → exit 1 (no match)
run_with_stub "$(gh_stub_rows '[]')" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: no comments → exit 1" 1 $?

# Stub: identity fetch fails → exit 2 (fetch-failed)
run_with_stub "$IDENTITY_FAIL_STUB" pr::has_coderails_review_for_head 42 "deadbeef"
rc=$?
check "has_coderails_review_for_head: identity fetch failure → exit 2 (fail-closed)" 2 $rc

# Stub: comments fetch fails (identity ok) → exit 2 (fetch-failed)
run_with_stub "$COMMENTS_FAIL_STUB" pr::has_coderails_review_for_head 42 "deadbeef"
rc=$?
check "has_coderails_review_for_head: comments fetch failure → exit 2 (fail-closed)" 2 $rc

# ─── Clean-break: the capped gh pr view --json comments fetch is fully gone ──
count=$(grep -c 'pr view --json comments' "$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/git-common.sh")
check "clean-break: no remaining 'gh pr view --json comments' call in git-common.sh" 0 "$count"

# ─── Pagination: a matching marker beyond the 100th comment row is found ────
# Build 105 filler rows (untrusted, non-matching) then a 106th trusted OWNER
# row carrying the real marker — proves the reader isn't silently truncating
# to the first 100 comments the way `gh pr view --json comments` did.
build_many_rows() {
    local i rows="["
    for ((i = 1; i <= 105; i++)); do
        rows+="$(comment_row "filler-$i" NONE "not a marker"),"
    done
    rows+="$(comment_row "$TRUSTED_LOGIN" OWNER "$GOOD_MARKER")"
    rows+="]"
    printf '%s' "$rows"
}
ROWS_BEYOND_100=$(build_many_rows)
run_with_stub "$(gh_stub_rows "$ROWS_BEYOND_100")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: marker beyond row 100 is still found (pagination)" 0 $?

# Negative control: same 106-row set but WITHOUT the trailing matching row →
# exit 1, proving the pagination test can actually detect a miss.
build_many_rows_no_match() {
    local i rows="["
    for ((i = 1; i <= 105; i++)); do
        rows+="$(comment_row "filler-$i" NONE "not a marker")"
        [[ $i -lt 105 ]] && rows+=","
    done
    rows+="]"
    printf '%s' "$rows"
}
ROWS_BEYOND_100_NO_MATCH=$(build_many_rows_no_match)
run_with_stub "$(gh_stub_rows "$ROWS_BEYOND_100_NO_MATCH")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: negative control — no matching row → exit 1" 1 $?

# ─── pr::has_coderails_eval_for_head ─────────────────────────────────────────
EVAL_ARTIFACT_LIB="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/eval-artifact.sh"
source "$EVAL_ARTIFACT_LIB"

GO_MARKER=$(eval_artifact::marker 42 "deadbeef" GO 1)
NOGO_MARKER=$(eval_artifact::marker 42 "deadbeef" NO-GO 2)
NOMATCH_MARKER=$(eval_artifact::marker 42 "othersha" GO 1)

# gh_stub_rows_eval: same shape as gh_stub_rows but matches "issues/*/comments"
# generically since the eval reader is exercised against both pr 42 and 999
# below (PR_EVAL_TIER leak test uses a second pr number).
gh_stub_rows_eval() {
    local rows="$1"
    cat <<STUB
case "\$*" in
  "api user -q .login")
    echo "$TRUSTED_LOGIN"
    ;;
  *"comments --paginate"*)
    printf '%s' '$rows' | jq -c '.[] | select(.user.login == "$TRUSTED_LOGIN" and .author_association == "OWNER") | (.body | @base64)' -r
    ;;
  *)
    exit 1
    ;;
esac
STUB
}

# Stub: comment body contains a matching GO marker from a trusted OWNER →
# exit 0, PR_EVAL_TIER set
ROWS_GO=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: trusted matching GO marker → rc=0" "rc=0" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: trusted matching GO marker → PR_EVAL_TIER=1" "tier=1" "$(printf '%s\n' "$result" | grep '^tier=')"

# E-spoof: untrusted login posts a byte-identical valid GO marker → exit 1 (rejected)
ROWS_SPOOF_GO=$(printf '[%s]' "$(comment_row "attacker" CONTRIBUTOR "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_SPOOF_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: untrusted GO marker → rc=1 (spoof rejected)" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: untrusted GO marker → PR_EVAL_TIER empty (never set from untrusted)" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# Stub: identity fetch fails → exit 2, PR_EVAL_TIER unset/empty
result=$(run_with_stub "$IDENTITY_FAIL_STUB" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: identity fetch fails → rc=2" "rc=2" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: identity fetch fails → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# Stub: comments fetch fails (identity ok) → exit 2, PR_EVAL_TIER unset/empty
result=$(run_with_stub "$COMMENTS_FAIL_STUB" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: comments fetch fails → rc=2" "rc=2" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: comments fetch fails → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# Stub: matching pr/sha but NO-GO → exit 1, PR_EVAL_TIER still set (so merge.sh can report it)
ROWS_NOGO=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$NOGO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_NOGO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: NO-GO marker → rc=1" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: NO-GO marker → PR_EVAL_TIER=2" "tier=2" "$(printf '%s\n' "$result" | grep '^tier=')"

# Stub: no matching marker at all → exit 1, PR_EVAL_TIER empty
ROWS_NOMATCH=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$NOMATCH_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_NOMATCH")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: no matching marker → rc=1" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: no matching marker → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# ─── has_coderails_eval_for_head: NEWEST-match-wins (not first-match-wins) ───
# A PR can accumulate multiple eval-artifact comments over its lifetime (e.g.
# a stale NO-GO from an earlier push, then a fresh GO after fixes). The LAST
# matching marker line in comment order must be authoritative — a stale GO
# must never override a newer NO-GO for the same sha, and the legit
# NO-GO→fix→GO path must still pass because GO is newest. All rows here are
# trusted OWNER comments — this section tests newest-wins in isolation from
# the author filter.

# (a) GO comment then NO-GO comment (same pr/sha, trusted) → newest (NO-GO) wins → rc=1
ROWS_GO_THEN_NOGO=$(printf '[%s,%s]' \
    "$(comment_row "$TRUSTED_LOGIN" OWNER "$GO_MARKER")" \
    "$(comment_row "$TRUSTED_LOGIN" OWNER "$NOGO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_GO_THEN_NOGO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: GO then NO-GO (same sha) → rc=1 (newest wins)" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: GO then NO-GO (same sha) → PR_EVAL_TIER=2 (from newest)" "tier=2" "$(printf '%s\n' "$result" | grep '^tier=')"

# (b) NO-GO comment then GO comment (same pr/sha, legit fix-and-repost path) → newest (GO) wins → rc=0
ROWS_NOGO_THEN_GO=$(printf '[%s,%s]' \
    "$(comment_row "$TRUSTED_LOGIN" OWNER "$NOGO_MARKER")" \
    "$(comment_row "$TRUSTED_LOGIN" OWNER "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_NOGO_THEN_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: NO-GO then GO (same sha) → rc=0 (newest wins)" "rc=0" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: NO-GO then GO (same sha) → PR_EVAL_TIER=1 (from newest)" "tier=1" "$(printf '%s\n' "$result" | grep '^tier=')"

# (c) NEWEST-WINS SURVIVES the author filter: trusted older GO, trusted newer
# NO-GO, then an UNTRUSTED forged GO newer still → the forged row must be
# dropped before matching, so the trusted NO-GO remains the newest surviving
# match → rc=1, not rc=0.
ROWS_FORGED_NEWEST=$(printf '[%s,%s,%s]' \
    "$(comment_row "$TRUSTED_LOGIN" OWNER "$GO_MARKER")" \
    "$(comment_row "$TRUSTED_LOGIN" OWNER "$NOGO_MARKER")" \
    "$(comment_row "attacker" CONTRIBUTOR "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_FORGED_NEWEST")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: trusted GO, trusted NO-GO, then FORGED newer GO → rc=1 (forgery ignored, newest-wins survives)" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: forged newer GO ignored → PR_EVAL_TIER=2 (from newest TRUSTED match)" "tier=2" "$(printf '%s\n' "$result" | grep '^tier=')"

# ─── has_coderails_eval_for_head: PR_EVAL_TIER does not leak across calls ────
# The function must unset PR_EVAL_TIER at entry so a second, non-matching call
# in the same shell can't inherit a stale value from a prior matching call.
# Second call targets a different pr/sha with the SAME rows (no matching
# marker for pr=999), so any leaked tier would surface as a false positive.
result=$(run_with_stub "$(gh_stub_rows_eval "$ROWS_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef" >/dev/null 2>&1
  pr::has_coderails_eval_for_head 999 "othersha" >/dev/null 2>&1
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: second no-match call in same shell → rc=1" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: second no-match call → PR_EVAL_TIER does not leak from first call" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
