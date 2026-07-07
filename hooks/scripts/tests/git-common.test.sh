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

# ─── repo(): a dotted repo name must not be truncated at the first dot ───────
# The capture used to be [^/.]+, which stops at the first dot, so
# owner/my.repo.git resolved to "owner/my" instead of "owner/my.repo".
DOTREPO="$TMP/dotrepo"; git init -q "$DOTREPO"
git -C "$DOTREPO" remote add origin "https://github.com/someowner/my.repo.git"
check "repo(): dotted repo name is captured in full, .git suffix stripped" \
  "someowner/my.repo" "$( cd "$DOTREPO" && repo )"

# ─── pr::head_sha + pr::has_coderails_review_for_head ───────────────────────
# These helpers call `gh`. Stub it via a PATH-injected fake script.
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR"
# Every gh_stub_rows invocation logs its own "$@" here (one line per call), so
# a test can assert the exact fetch shape production used (--paginate, the
# issues/<n>/comments path) instead of only inferring it indirectly.
STUB_ARGS_LOG="$TMP/gh.args.log"

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
# Both gate readers now call `gh` three times: `gh api user -q .login`
# (identity, once per process), `gh repo view ... --json viewerPermission -q
# .viewerPermission` (permission, once per process), and the paginated REST
# comments fetch `gh api repos/{owner}/{repo}/issues/{n}/comments --paginate
# --jq '...'`. comment_row() builds one raw JSON comment object; gh_stub_rows()
# builds a stub `gh` script that branches on "$@": returns TRUSTED_LOGIN for
# `api user`, a caller-chosen permission level for `repo view ...
# viewerPermission`, and for the comments fetch EXTRACTS the --jq program
# production actually passed out of its own "$@" and executes it verbatim with
# real `jq -r` over the fixture rows. This means the filter logic lives ONLY in
# git-common.sh — the stub never re-guesses or duplicates the select
# expression, so a mutation that weakens or deletes the production filter
# changes what these tests observe (proven by the negative control below,
# where deleting the filter from production makes the spoof tests fail).
TRUSTED_LOGIN="trusted-bot"

# comment_row <login> <assoc> <body>
# Echoes one JSON object for the comments array (body is JSON-string-escaped
# via jq -Rs so embedded newlines/quotes in a marker+prose body are safe).
# author_association is retained in the fixture shape (real GitHub payloads
# carry it) even though production no longer filters on it — this
# lets PERMISSION-TRUST exercise a non-OWNER association (MEMBER) explicitly.
comment_row() {
    local login="$1" assoc="$2" body="$3"
    local body_json; body_json=$(printf '%s' "$body" | jq -Rs .)
    printf '{"user":{"login":"%s"},"author_association":"%s","body":%s}' "$login" "$assoc" "$body_json"
}

# gh_stub_rows <rows_json_array> [permission]
# Builds a gh stub body (to hand to run_with_stub) that serves TRUSTED_LOGIN
# for identity, [permission] (default WRITE — sufficient trust, so every
# pre-existing call site that doesn't pass this argument keeps its original
# behaviour unchanged) for the viewerPermission lookup, and for the comments
# fetch pulls the --jq argument out of its own "$@" (the exact program
# production passed) and runs it for real with `jq -r` over the given JSON
# array of comment rows. Matches any "*/comments --paginate*" invocation
# generically (both readers use it, across different pr numbers), since the
# stub no longer needs to special-case pr=42. Every invocation appends its own
# "$@" (one call per line) to $STUB_ARGS_LOG so a test can assert exactly what
# production invoked, instead of only inferring it from the case-match
# succeeding.
gh_stub_rows() {
    local rows="$1" permission="${2:-WRITE}"
    cat <<STUB
args=("\$@")
printf '%s\n' "\$*" >> "$STUB_ARGS_LOG"
case "\$*" in
  "api user -q .login")
    echo "$TRUSTED_LOGIN"
    ;;
  *"viewerPermission"*)
    echo "$permission"
    ;;
  *"comments --paginate"*)
    # Find the --jq program among our own args and execute it verbatim —
    # this is what makes the test exercise production's actual filter.
    for ((i = 0; i < \${#args[@]}; i++)); do
        if [[ "\${args[\$i]}" == "--jq" ]]; then
            jq_prog="\${args[\$((i + 1))]}"
            printf '%s' '$rows' | jq -r "\$jq_prog"
            exit 0
        fi
    done
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
STUB
}

# gh_stub_identity_fail
# Identity fetch itself fails (gh api user exits non-zero) — permission and
# comments calls never have a chance to run.
IDENTITY_FAIL_STUB='case "$*" in
  "api user -q .login") exit 1 ;;
  *) exit 1 ;;
esac'

# gh_stub_permission_fail
# Identity succeeds but the permission (viewerPermission) lookup fails —
# comments call never has a chance to run.
PERMISSION_FAIL_STUB="case \"\$*\" in
  \"api user -q .login\") echo \"$TRUSTED_LOGIN\" ;;
  *\"viewerPermission\"*) exit 1 ;;
  *) exit 1 ;;
esac"

# gh_stub_comments_fail
# Identity and permission succeed (WRITE) but the comments fetch fails.
COMMENTS_FAIL_STUB="case \"\$*\" in
  \"api user -q .login\") echo \"$TRUSTED_LOGIN\" ;;
  *\"viewerPermission\"*) echo WRITE ;;
  *\"issues/42/comments --paginate\"*) exit 1 ;;
  *) exit 1 ;;
esac"

# Trust baseline: trusted OWNER posts a valid marker → exit 0
ROWS_TRUSTED_MATCH=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$GOOD_MARKER")")
: > "$STUB_ARGS_LOG"
run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_MATCH")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: trusted OWNER matching marker → exit 0" 0 $?

# Fetch-shape assertion: the comments fetch production actually issued must
# have used pagination and hit the issues/<n>/comments REST path — not just
# "matched some case branch", which a looser pattern could satisfy by accident.
FETCH_LINE=$(grep 'comments' "$STUB_ARGS_LOG" | tail -1)
check "has_coderails_review_for_head: comments fetch used --paginate" "true" \
  "$([[ "$FETCH_LINE" == *"--paginate"* ]] && echo true || echo false)"
check "has_coderails_review_for_head: comments fetch hit issues/42/comments" "true" \
  "$([[ "$FETCH_LINE" == *"issues/42/comments"* ]] && echo true || echo false)"

# Spoof rejection: untrusted login posts a byte-identical valid marker → exit 1.
# Permission defaults to WRITE in the stub: login-match alone must still reject
# a forged marker regardless of the (write-capable) permission field.
ROWS_SPOOF=$(printf '[%s]' "$(comment_row "attacker" CONTRIBUTOR "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_SPOOF")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: untrusted login byte-identical marker → exit 1 (spoof rejected)" 1 $?

# PERMISSION-TRUST: trusted login, NON-OWNER association (MEMBER — simulates
# an org-repo collaborator), write permission → exit 0. Trust comes from login
# identity and write permission, not an OWNER-badge conjunct.
ROWS_TRUSTED_MEMBER=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" MEMBER "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_MEMBER" WRITE)" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: trusted login, MEMBER association, write permission → exit 0 (org-collaborator now trusted)" 0 $?

# PERMISSION-DENY: trusted login but permission=READ → exit 1 (not trusted
# — proves this isn't a login-only check in disguise; permission genuinely gates).
ROWS_TRUSTED_READ=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" MEMBER "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_READ" READ)" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: trusted login, permission=READ → exit 1 (permission denies trust)" 1 $?

# Untrusted login WITH write permission → exit 1 (isolates the login check
# from the permission check — a permission-only filter would wrongly pass
# this, since write permission alone is satisfied; the login mismatch must
# still reject it)
ROWS_ATTACKER_WRITE=$(printf '[%s]' "$(comment_row "attacker" MEMBER "$GOOD_MARKER")")
run_with_stub "$(gh_stub_rows "$ROWS_ATTACKER_WRITE" WRITE)" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: untrusted login, write permission → exit 1 (login check isolated from permission check)" 1 $?

# FAIL-CLOSED: permission lookup itself fails → exit 2 (same fail-closed
# posture as the existing identity-fetch-failure contract).
run_with_stub "$PERMISSION_FAIL_STUB" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: permission lookup failure → exit 2 (fail-closed)" 2 $?

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

# ─── identity-fetch vs permission-fetch vs comments-fetch failure are
# distinguishable to the operator ─────────────────────────────────────────────
# The 0/1/2 return-code contract on the public reader functions is unchanged
# (both still return 2 for any of the three failure modes, asserted above and
# below) — the internal cause is surfaced via a global variable set by
# pr::_trusted_comment_bodies (mirrors the existing PR_EVAL_TIER pattern of a
# global set alongside a return code), so merge.sh's caller can print a
# message naming which fetch actually failed instead of always blaming
# "comments".
run_with_stub "$IDENTITY_FAIL_STUB" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_review_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "reason=${PR_TRUST_FETCH_FAIL_REASON:-}"
' > "$TMP/identity_fail.out"
check "has_coderails_review_for_head: identity fetch failure → exit 2" "rc=2" "$(grep '^rc=' "$TMP/identity_fail.out")"
check "has_coderails_review_for_head: identity fetch failure → reason=identity" "reason=identity" "$(grep '^reason=' "$TMP/identity_fail.out")"

run_with_stub "$PERMISSION_FAIL_STUB" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_review_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "reason=${PR_TRUST_FETCH_FAIL_REASON:-}"
' > "$TMP/permission_fail.out"
check "has_coderails_review_for_head: permission fetch failure → exit 2" "rc=2" "$(grep '^rc=' "$TMP/permission_fail.out")"
check "has_coderails_review_for_head: permission fetch failure → reason=permission" "reason=permission" "$(grep '^reason=' "$TMP/permission_fail.out")"

run_with_stub "$COMMENTS_FAIL_STUB" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_review_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "reason=${PR_TRUST_FETCH_FAIL_REASON:-}"
' > "$TMP/comments_fail.out"
check "has_coderails_review_for_head: comments fetch failure → exit 2" "rc=2" "$(grep '^rc=' "$TMP/comments_fail.out")"
check "has_coderails_review_for_head: comments fetch failure → reason=comments" "reason=comments" "$(grep '^reason=' "$TMP/comments_fail.out")"

check "identity-fail and comments-fail reasons are DISTINCT" "true" \
  "$([[ "$(grep '^reason=' "$TMP/identity_fail.out")" != "$(grep '^reason=' "$TMP/comments_fail.out")" ]] && echo true || echo false)"
check "permission-fail and comments-fail reasons are DISTINCT" "true" \
  "$([[ "$(grep '^reason=' "$TMP/permission_fail.out")" != "$(grep '^reason=' "$TMP/comments_fail.out")" ]] && echo true || echo false)"
check "identity-fail and permission-fail reasons are DISTINCT" "true" \
  "$([[ "$(grep '^reason=' "$TMP/identity_fail.out")" != "$(grep '^reason=' "$TMP/permission_fail.out")" ]] && echo true || echo false)"

# ─── an mktemp failure inside pr::_trusted_comment_bodies_or_fail must still
# fail-closed (exit 2) WITHOUT leaking a raw, unguarded coreutils error past
# the TRUST_FETCH_FAIL_REASON abstraction. A fake failing `mktemp` on PATH
# (alongside the normal gh stub) reproduces "no writable temp dir" — the
# wrapper must detect the failure itself and report a dedicated reason rather
# than silently proceeding with an empty/invalid stderr_file path.
MKTEMP_FAIL_STUB_DIR="$TMP/mktemp_fail_stubs"
mkdir -p "$MKTEMP_FAIL_STUB_DIR"
cat > "$MKTEMP_FAIL_STUB_DIR/mktemp" <<'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$MKTEMP_FAIL_STUB_DIR/mktemp"
GH_STUB="$STUB_DIR/gh"
printf '#!/bin/bash\n%s\n' "$(gh_stub_rows "$ROWS_TRUSTED_MATCH")" > "$GH_STUB"
chmod +x "$GH_STUB"
result=$(
  export PATH="$MKTEMP_FAIL_STUB_DIR:$STUB_DIR:$PATH"
  bash -c '
    source "'"$LIB"'"
    pr::has_coderails_review_for_head 42 "deadbeef"
    echo "rc=$?"
    echo "reason=${PR_TRUST_FETCH_FAIL_REASON:-}"
  ' 2>"$TMP/mktemp_fail_stderr.out"
)
check "has_coderails_review_for_head: mktemp failure → exit 2 (fail-closed, not silently bypassed)" "rc=2" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_review_for_head: mktemp failure → a distinct reason is set (not empty/unset)" "true" \
  "$([[ -n "$(printf '%s\n' "$result" | sed -n 's/^reason=//p')" ]] && echo true || echo false)"
check "has_coderails_review_for_head: mktemp failure → no raw coreutils error text reaches stderr" "true" \
  "$(grep -qi 'no such file or directory' "$TMP/mktemp_fail_stderr.out" && echo false || echo true)"

# ─── Injection: a pre-seeded _PR_TRUSTED_LOGIN must be validated, not trusted
# blindly ──────────────────────────────────────────────────────────────────
# pr::_trusted_login skips the gh fetch when _PR_TRUSTED_LOGIN is already set
# (its per-subshell reuse guard). If that pre-seeded value were spliced
# unvalidated into the --jq program, a value like `x" or true` would break out
# of the string literal and make the trust filter match everything (fail-open).
# The stub here would only serve a fixture with an "attacker"-authored marker,
# so the ONLY way this could return exit 0 is if the malicious login bypassed
# the select. A rejected login makes pr::_trusted_login fail exactly like a
# failed gh fetch, so the reader fails closed the same way, via exit 2.
export _PR_TRUSTED_LOGIN='x" or true'
run_with_stub "$(gh_stub_rows "$ROWS_SPOOF")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: malicious pre-seeded _PR_TRUSTED_LOGIN is rejected (fail-closed, not spliced into jq)" 2 $?
unset _PR_TRUSTED_LOGIN

# ─── Clean-break: the capped gh pr view --json comments fetch is fully gone ──
# The old code read `gh pr view "$num" --json comments` — the PR number sits
# BETWEEN `view` and `--json`, so a literal 'pr view --json comments' string
# never matched it even before this fix and would pass vacuously against
# unchanged old code. Use a regex that bridges the argument instead.
GIT_COMMON_SH="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/git-common.sh"
count=$(grep -cE 'pr view .*--json comments' "$GIT_COMMON_SH")
check "clean-break: no remaining 'gh pr view ... --json comments' call in git-common.sh" 0 "$count"

# Control: the SAME -E pattern must find the old call in the pre-change blob,
# proving this guard can actually fail (i.e. it isn't vacuous the way the
# literal-string version was). Skipped gracefully if the commit isn't
# reachable (e.g. a shallow clone) rather than failing the suite.
OLD_BLOB_SHA="7aab163b59481ddb94dd6324375b4155f2014582"
if old_blob=$(git show "${OLD_BLOB_SHA}:scripts/lib/git-common.sh" 2>/dev/null); then
    old_count=$(printf '%s\n' "$old_blob" | grep -cE 'pr view .*--json comments')
    check "clean-break control: -E pattern finds the old call in the pre-change blob (guard is not vacuous)" "true" \
      "$([[ "$old_count" -ge 1 ]] && echo true || echo false)"
else
    echo "skip - clean-break control: pre-change commit $OLD_BLOB_SHA not reachable (shallow clone?)"
fi

# ─── CLEAN-BREAK NEGATIVE CONTROL: the OWNER-badge conjunct is fully gone,
# no compat flag, no dual-path fallback ───────────────────────────────────────
owner_conjunct_count=$(grep -c 'author_association == "OWNER"' "$GIT_COMMON_SH")
check "clean-break: no remaining 'author_association == \"OWNER\"' conjunct in git-common.sh" 0 "$owner_conjunct_count"

# Control: the SAME pattern must find the old conjunct in the pre-change (frozen)
# blob, proving the guard can actually fail rather than being vacuous.
FREEZE_SHA="238f5e14c788503e9d194ac9afdba5749dd88c92"
if old_blob_owner=$(git show "${FREEZE_SHA}:scripts/lib/git-common.sh" 2>/dev/null); then
    old_owner_count=$(printf '%s\n' "$old_blob_owner" | grep -c 'author_association == "OWNER"')
    check "clean-break control: conjunct present in the frozen pre-change blob (guard is not vacuous)" "true" \
      "$([[ "$old_owner_count" -ge 1 ]] && echo true || echo false)"
else
    echo "skip - clean-break control: frozen commit $FREEZE_SHA not reachable (shallow clone?)"
fi

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

# ─── Multi-line body: marker on its own line, surrounded by prose ───────────
# Every fixture body so far has been a bare marker line. Production base64-
# encodes each body specifically so a multi-line comment survives as a single
# reader line (see pr::_trusted_comment_bodies) and the marker is then matched
# line-by-line within it — this is the real-world shape (a human/bot writes
# prose around the marker), so it must be exercised at least once.
MULTILINE_BODY=$'Some prose before the marker.\n'"$GOOD_MARKER"$'\nSome prose after the marker.'
ROWS_MULTILINE=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$MULTILINE_BODY")")
run_with_stub "$(gh_stub_rows "$ROWS_MULTILINE")" pr::has_coderails_review_for_head 42 "deadbeef"
check "has_coderails_review_for_head: marker on its own line within a multi-line prose body → exit 0" 0 $?

# ─── pr::has_coderails_eval_for_head ─────────────────────────────────────────
EVAL_ARTIFACT_LIB="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/eval-artifact.sh"
source "$EVAL_ARTIFACT_LIB"

GO_MARKER=$(eval_artifact::marker 42 "deadbeef" GO 1)
NOGO_MARKER=$(eval_artifact::marker 42 "deadbeef" NO-GO 2)
NOMATCH_MARKER=$(eval_artifact::marker 42 "othersha" GO 1)

# The eval reader is exercised against both pr 42 and 999 (PR_EVAL_TIER leak
# test uses a second pr number) — gh_stub_rows already matches "comments
# --paginate" generically, so it's reused here rather than duplicated.

# Stub: comment body contains a matching GO marker from a trusted OWNER →
# exit 0, PR_EVAL_TIER set
ROWS_GO=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$GO_MARKER")")
: > "$STUB_ARGS_LOG"
result=$(run_with_stub "$(gh_stub_rows "$ROWS_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: trusted matching GO marker → rc=0" "rc=0" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: trusted matching GO marker → PR_EVAL_TIER=1" "tier=1" "$(printf '%s\n' "$result" | grep '^tier=')"

# Fetch-shape assertion: same as the review reader's, proving the eval reader
# also issues a paginated issues/<n>/comments fetch (both readers share
# pr::_trusted_comment_bodies, but this exercises it from the eval call site).
FETCH_LINE_EVAL=$(grep 'comments' "$STUB_ARGS_LOG" | tail -1)
check "has_coderails_eval_for_head: comments fetch used --paginate" "true" \
  "$([[ "$FETCH_LINE_EVAL" == *"--paginate"* ]] && echo true || echo false)"
check "has_coderails_eval_for_head: comments fetch hit issues/42/comments" "true" \
  "$([[ "$FETCH_LINE_EVAL" == *"issues/42/comments"* ]] && echo true || echo false)"

# E-spoof: untrusted login posts a byte-identical valid GO marker → exit 1 (rejected)
ROWS_SPOOF_GO=$(printf '[%s]' "$(comment_row "attacker" CONTRIBUTOR "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows "$ROWS_SPOOF_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: untrusted GO marker → rc=1 (spoof rejected)" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: untrusted GO marker → PR_EVAL_TIER empty (never set from untrusted)" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# Spoof rejection: untrusted login WITH write permission → rc=1 (isolates the login
# check from the permission check, same as the review reader's equivalent)
ROWS_ATTACKER_WRITE_GO=$(printf '[%s]' "$(comment_row "attacker" MEMBER "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows "$ROWS_ATTACKER_WRITE_GO" WRITE)" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: untrusted login, write permission → rc=1 (login check isolated from permission check)" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: untrusted login, write permission → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# PERMISSION-TRUST (eval reader): trusted login, non-OWNER (MEMBER)
# association, write permission → rc=0 (org-collaborator trusted — mirrors
# the review reader's equivalent behaviour)
ROWS_TRUSTED_MEMBER_GO=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" MEMBER "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_MEMBER_GO" WRITE)" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: trusted login, MEMBER association, write permission → rc=0" "rc=0" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: trusted login, MEMBER association, write permission → PR_EVAL_TIER=1" "tier=1" "$(printf '%s\n' "$result" | grep '^tier=')"

# PERMISSION-DENY (eval reader): trusted login but permission=READ → rc=1
# (proves permission genuinely gates, not a login-only check in disguise)
ROWS_TRUSTED_READ_GO=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" MEMBER "$GO_MARKER")")
result=$(run_with_stub "$(gh_stub_rows "$ROWS_TRUSTED_READ_GO" READ)" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: trusted login, permission=READ → rc=1 (permission denies trust)" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: trusted login, permission=READ → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# FAIL-CLOSED (eval reader): permission lookup itself fails → rc=2
result=$(run_with_stub "$PERMISSION_FAIL_STUB" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: permission lookup failure → rc=2 (fail-closed)" "rc=2" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: permission lookup failure → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# Stub: no comments (empty array) → rc=1, PR_EVAL_TIER unset (mirrors the
# review reader's empty-comment-list case, for the eval reader too)
result=$(run_with_stub "$(gh_stub_rows '[]')" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: no comments → rc=1" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: no comments → PR_EVAL_TIER empty" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

# Multi-line body: GO marker on its own line, surrounded by prose (mirrors the
# review reader's equivalent — every eval fixture so far has been a bare
# marker line too).
MULTILINE_GO_BODY=$'## Eval summary\n\n'"$GO_MARKER"$'\n\nSee PR for details.'
ROWS_MULTILINE_GO=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$MULTILINE_GO_BODY")")
result=$(run_with_stub "$(gh_stub_rows "$ROWS_MULTILINE_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: GO marker on its own line within a multi-line prose body → rc=0" "rc=0" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: GO marker within multi-line body → PR_EVAL_TIER=1" "tier=1" "$(printf '%s\n' "$result" | grep '^tier=')"

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
result=$(run_with_stub "$(gh_stub_rows "$ROWS_NOGO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef"
  echo "rc=$?"
  echo "tier=$PR_EVAL_TIER"
')
check "has_coderails_eval_for_head: NO-GO marker → rc=1" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: NO-GO marker → PR_EVAL_TIER=2" "tier=2" "$(printf '%s\n' "$result" | grep '^tier=')"

# Stub: no matching marker at all → exit 1, PR_EVAL_TIER empty
ROWS_NOMATCH=$(printf '[%s]' "$(comment_row "$TRUSTED_LOGIN" OWNER "$NOMATCH_MARKER")")
result=$(run_with_stub "$(gh_stub_rows "$ROWS_NOMATCH")" bash -c '
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
result=$(run_with_stub "$(gh_stub_rows "$ROWS_GO_THEN_NOGO")" bash -c '
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
result=$(run_with_stub "$(gh_stub_rows "$ROWS_NOGO_THEN_GO")" bash -c '
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
result=$(run_with_stub "$(gh_stub_rows "$ROWS_FORGED_NEWEST")" bash -c '
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
result=$(run_with_stub "$(gh_stub_rows "$ROWS_GO")" bash -c '
  source "'"$LIB"'"
  pr::has_coderails_eval_for_head 42 "deadbeef" >/dev/null 2>&1
  pr::has_coderails_eval_for_head 999 "othersha" >/dev/null 2>&1
  echo "rc=$?"
  echo "tier=${PR_EVAL_TIER:-}"
')
check "has_coderails_eval_for_head: second no-match call in same shell → rc=1" "rc=1" "$(printf '%s\n' "$result" | grep '^rc=')"
check "has_coderails_eval_for_head: second no-match call → PR_EVAL_TIER does not leak from first call" "tier=" "$(printf '%s\n' "$result" | grep '^tier=')"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
