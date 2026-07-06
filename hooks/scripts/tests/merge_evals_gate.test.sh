#!/bin/bash
# Behavioural tests for the eval-artifact gate in scripts/merge.sh — the gate
# inserted directly after the existing review-artifact gate. Mirrors
# merge.test.sh's stub-dir/wrapper technique, additionally stubbing
# pr::has_coderails_eval_for_head to control its exit code and PR_EVAL_TIER.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MERGE_SH="$REPO_ROOT/scripts/merge.sh"
TMP=$(mktemp -d)
trap 'chmod -R u+w "$TMP" 2>/dev/null; find "$TMP" -maxdepth 3 -type f -delete 2>/dev/null; rmdir "$TMP"/* "$TMP" 2>/dev/null || true' EXIT

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_msg() { # desc pattern output
  if echo "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected pattern: %s\n  actual output:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── Build a stub dir that merge.sh will source ──────────────────────────────
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR/lib"

# Stub config.sh
cat > "$STUB_DIR/lib/config.sh" <<'CONFIGSTUB'
#!/bin/bash
coderails::config_path() { echo ""; }
coderails::resolve_config() { echo "NO_CONFIG"; }
CONFIGSTUB

# Stub git-common.sh base (always constant)
cat > "$STUB_DIR/lib/git-common-base.sh" <<'BASELIB'
#!/bin/bash
readonly C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_BLD='' C_RST='' 2>/dev/null || true
info()    { :; }
ok()      { :; }
warn()    { :; }
err()     { printf '%s\n' "$1" >&2; exit 1; }
dim()     { :; }
step()    { :; }
banner()  { :; }

branch()  { echo "feature/test"; }
dirty()   { return 1; }
clean()   { return 0; }
main()    { echo "main"; }

repo()    { echo "test-owner/test-repo"; }
protected() { return 1; }
sync::main_branch() { return 0; }

require::feature() { return 0; }
require::clean()   { return 0; }
require::repo()    { return 0; }

pr::num()    { echo "42"; }
pr::url()    { echo "https://github.com/test-owner/test-repo/pull/42"; }
pr::state()  { echo "OPEN"; }
pr::title()  { echo "Test PR"; }
pr::review() { echo "APPROVED"; }
pr::exists() { return 0; }
BASELIB

# Stub gh (for the post-merge branch-delete step)
cat > "$STUB_DIR/gh" <<'GHSTUB'
#!/bin/bash
case "$*" in
  *"pr merge"*) exit 0 ;;
  *"pr view"*"headRefName"*) printf '{"headRefName":"feature/test"}\n' ;;
  *) exit 0 ;;
esac
GHSTUB
chmod +x "$STUB_DIR/gh"

# git stub: branch push --delete should silently succeed
cat > "$STUB_DIR/git" <<'GITSTUB'
#!/bin/bash
case "$*" in
  *"push origin --delete"*) exit 0 ;;
  *"branch -D"*) exit 0 ;;
  *) exec /usr/bin/git "$@" ;;
esac
GITSTUB
chmod +x "$STUB_DIR/git"

# run_evals_gate_test: <review_exit> <eval_exit> <eval_tier> [trust_fail_reason]
# Always uses a valid sha/review pass so only the eval gate's behaviour varies,
# unless review_exit is set nonzero to prove short-circuit ordering.
# [trust_fail_reason] (identity/permission/comments) lets a test assert
# merge.sh's eval-gate case-branch message names the real cause (WU4).
run_evals_gate_test() {
    local review_exit="$1" eval_exit="$2" eval_tier="$3" trust_fail_reason="${4:-}"
    local stderr_file="$TMP/stderr_run"
    local stdout_file="$TMP/stdout_run"

    cat > "$STUB_DIR/lib/git-common.sh" <<GCSTUB
#!/bin/bash
source "$STUB_DIR/lib/git-common-base.sh"

pr::head_sha() {
    echo "deadbeef"
}

pr::has_coderails_review_for_head() {
    return ${review_exit}
}

pr::has_coderails_eval_for_head() {
    PR_EVAL_TIER="${eval_tier}"
    PR_TRUST_FETCH_FAIL_REASON="${trust_fail_reason}"
    [[ -z "\${PR_TRUST_FETCH_FAIL_REASON}" ]] && unset PR_TRUST_FETCH_FAIL_REASON
    return ${eval_exit}
}
GCSTUB

    local wrapper="$STUB_DIR/merge_test.sh"
    cat > "$wrapper" <<WRAPPER
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common.sh"
source "\$_DIR/lib/config.sh"
WRAPPER
    awk '
        NR==1 { next }
        /^source.*git-common/ { next }
        /^source.*config/ { next }
        { print }
    ' "$MERGE_SH" >> "$wrapper"

    (
        export PATH="$STUB_DIR:$PATH"
        bash "$wrapper" 42 2>"$stderr_file" >"$stdout_file"
    )
    local rc=$?
    LAST_STDERR=$(cat "$stderr_file" 2>/dev/null || true)
    LAST_STDOUT=$(cat "$stdout_file" 2>/dev/null || true)
    return $rc
}

# ─── Negative control: prove the pre-extension gap ───────────────────────────
# review gate passes (0), eval gate would block (1) — but merge.sh does not
# call the eval gate yet at this point in the TDD cycle, so merge wrongly
# proceeds. This documents the gap the new gate closes.
# (This section is run once, before the fix, to prove the gap — see report.)

# ─── Test 1: both gates pass → merge proceeds (exit 0) ───────────────────────
run_evals_gate_test 0 0 1
check "merge proceeds when both review and eval gates pass" 0 $?

# ─── Test 2: no eval artifact (eval_exit=1, no tier) → merge blocks ──────────
run_evals_gate_test 0 1 ""
rc=$?
check "merge blocks when no eval artifact found" 1 $rc
check_msg "merge: no-artifact message mentions 'No coderails eval artifact'" "No coderails eval artifact" "$LAST_STDERR"
check_msg "merge: no-artifact message names current head sha" "deadbeef" "$LAST_STDERR"

# ─── Test 3: NO-GO eval artifact (eval_exit=1, tier=1) → merge blocks, names tier ──
run_evals_gate_test 0 1 1
rc=$?
check "merge blocks on NO-GO eval artifact" 1 $rc
check_msg "merge: NO-GO message mentions NO-GO" "NO-GO" "$LAST_STDERR"
check_msg "merge: NO-GO message names tier 1" "tier 1" "$LAST_STDERR"

# ─── Test 4: gh fetch failed for eval gate (eval_exit=2) → merge blocks distinctly ──
run_evals_gate_test 0 2 ""
rc=$?
check "merge blocks on eval-gate gh fetch failure" 1 $rc
check_msg "merge: eval fetch-fail message mentions GitHub fetch" "GitHub fetch" "$LAST_STDERR"
check_msg "merge: eval fetch-fail message mentions eval artifact" "eval artifact" "$LAST_STDERR"

# ─── Test 4b/4c (WU4): eval-gate identity/permission reasons produce distinct,
# cause-naming messages, not the generic fallback ─────────────────────────────
run_evals_gate_test 0 2 "" identity
rc=$?
check "merge blocks on eval-gate identity-fetch failure" 1 $rc
check_msg "merge: eval identity-fetch-fail message names the identity cause" "authenticated identity" "$LAST_STDERR"

run_evals_gate_test 0 2 "" permission
rc=$?
check "merge blocks on eval-gate permission-fetch failure" 1 $rc
check_msg "merge: eval permission-fetch-fail message names the permission cause" "repo permission" "$LAST_STDERR"

run_evals_gate_test 0 2 "" identity
EVAL_IDENTITY_MSG="$LAST_STDERR"
run_evals_gate_test 0 2 "" permission
EVAL_PERMISSION_MSG="$LAST_STDERR"
run_evals_gate_test 0 2 ""
EVAL_FALLBACK_MSG="$LAST_STDERR"
check "merge: eval-gate identity and permission fetch-fail messages are DISTINCT" "true" \
  "$([[ "$EVAL_IDENTITY_MSG" != "$EVAL_PERMISSION_MSG" ]] && echo true || echo false)"
check "merge: eval-gate identity and fallback fetch-fail messages are DISTINCT" "true" \
  "$([[ "$EVAL_IDENTITY_MSG" != "$EVAL_FALLBACK_MSG" ]] && echo true || echo false)"
check "merge: eval-gate permission and fallback fetch-fail messages are DISTINCT" "true" \
  "$([[ "$EVAL_PERMISSION_MSG" != "$EVAL_FALLBACK_MSG" ]] && echo true || echo false)"

# ─── Test 4d (Loop 2 WU-B1): PR_TRUST_FETCH_FAIL_REASON=tempfile on the
# eval-artifact gate, mirroring Test 3d in merge.test.sh for the review gate.
run_evals_gate_test 0 2 "" tempfile
rc=$?
check "merge blocks on eval-gate tempfile-allocation failure" 1 $rc
check_msg "merge: eval tempfile-fail message names the tempfile/local cause" "temporary file" "$LAST_STDERR"

run_evals_gate_test 0 2 "" tempfile
EVAL_TEMPFILE_MSG="$LAST_STDERR"
run_evals_gate_test 0 2 ""
EVAL_FALLBACK_MSG_2="$LAST_STDERR"
check "merge: eval-gate tempfile and fallback fetch-fail messages are DISTINCT" "true" \
  "$([[ "$EVAL_TEMPFILE_MSG" != "$EVAL_FALLBACK_MSG_2" ]] && echo true || echo false)"
check "merge: eval-gate tempfile and identity fetch-fail messages are DISTINCT" "true" \
  "$([[ "$EVAL_TEMPFILE_MSG" != "$EVAL_IDENTITY_MSG" ]] && echo true || echo false)"

# ─── Test 5: NO-GO at tier 0 (defensive case — shouldn't normally happen) ────
run_evals_gate_test 0 1 0
rc=$?
check "merge blocks on NO-GO at tier 0 (defensive)" 1 $rc
check_msg "merge: tier-0 NO-GO message names tier 0" "tier 0" "$LAST_STDERR"

# ─── Test 6: gate order — review gate blocks first, eval gate never runs ─────
# Stub pr::has_coderails_eval_for_head to exit 99 if called at all, proving
# short-circuit: the review gate's err() calls `exit 1` before this line runs.
cat > "$STUB_DIR/lib/git-common.sh" <<GCSTUB
#!/bin/bash
source "$STUB_DIR/lib/git-common-base.sh"

pr::head_sha() {
    echo "deadbeef"
}

pr::has_coderails_review_for_head() {
    return 1
}

pr::has_coderails_eval_for_head() {
    exit 99
}
GCSTUB

wrapper="$STUB_DIR/merge_test.sh"
cat > "$wrapper" <<WRAPPER
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common.sh"
source "\$_DIR/lib/config.sh"
WRAPPER
awk '
    NR==1 { next }
    /^source.*git-common/ { next }
    /^source.*config/ { next }
    { print }
' "$MERGE_SH" >> "$wrapper"

(
    export PATH="$STUB_DIR:$PATH"
    bash "$wrapper" 42 2>"$TMP/stderr_order" >"$TMP/stdout_order"
)
rc=$?
order_stderr=$(cat "$TMP/stderr_order" 2>/dev/null || true)
check "merge blocks on review-artifact message when review gate fails first" 1 $rc
check_msg "merge: review-gate-first message mentions post-review" "post-review" "$order_stderr"
[[ "$rc" -ne 99 ]]
check "merge: eval gate never reached (rc is not the 99 sentinel)" 0 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
