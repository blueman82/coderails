#!/bin/bash
# Behavioural tests for scripts/tier-gate/tier-gate-runner.sh — the root-daemon
# poll/judge/post lifecycle. Stubs `gh` on PATH (never a real network call) and
# redefines tg_judge per-test (late-bound function, resolved at call time) to
# control the verdict path independent of Task 3's real implementation.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNNER="$REPO_ROOT/scripts/tier-gate/tier-gate-runner.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
check() { # desc expected actual
    if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_contains() { # desc pattern haystack
    if printf '%s' "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected to contain: %s\n  actual: %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_not_contains() { # desc pattern haystack
    if printf '%s' "$3" | grep -qF "$2"; then
        printf 'FAIL - %s\n  expected NOT to contain: %s\n  actual: %s\n' "$1" "$2" "$3"; fails=$((fails+1))
    else printf 'ok   - %s\n' "$1"
    fi
}

# ─── Source the runner (main-guard prevents the poll loop from running) ──────
source "$RUNNER"

# ─── Fixture bodies (Task 4 embed contract: marker line + fenced json) ───────
tier0_body() { # <pr> <sha> <result>
    local pr="$1" sha="$2" result="$3"
    printf '<!-- coderails-eval-summary v1 pr=%s head_sha=%s result=%s tier=0 -->\n```json\n{"tier":0,"tier_justification":"x","evals":[],"head_sha":"%s"}\n```\n' "$pr" "$sha" "$result" "$sha"
}
tier1_body() { # <pr> <sha> <result>
    local pr="$1" sha="$2" result="$3"
    printf '<!-- coderails-eval-summary v1 pr=%s head_sha=%s result=%s tier=1 -->\n```json\n{"tier":1,"tier_justification":"x","evals":[{"id":"e1","priority":"P0","status":"pass"}],"head_sha":"%s"}\n```\n' "$pr" "$sha" "$result" "$sha"
}

# ─── gh stub factory ──────────────────────────────────────────────────────────
# STATUSES_JSON / HEAD_SHA / COMMENT_BODY / POSTED (log file) are set per test.
STATUSES_FILE="$TMP/statuses.json"
POSTED_LOG="$TMP/posted.log"
COMMENT_B64_FILE="$TMP/comment.b64"

reset_gh_state() {
    printf '[]' > "$STATUSES_FILE"
    : > "$POSTED_LOG"
    : > "$COMMENT_B64_FILE"
}

write_gh_stub() {
    cat > "$TMP/gh" <<GHSTUB
#!/bin/bash
case "\$*" in
  *"pr list --state open"*)
    echo "$TEST_PR"
    ;;
  *"pr view"*"headRefOid"*)
    echo "$TEST_SHA"
    ;;
  *"issues/${TEST_PR:-x}/comments"*)
    cat "$COMMENT_B64_FILE"
    ;;
  *"commits/"*"/statuses"*)
    cat "$STATUSES_FILE"
    ;;
  *"statuses/"*)
    # gh api repos/.../statuses/<sha> -f state=... -f context=... -f description=...
    args="\$*"
    state=\$(printf '%s' "\$args" | grep -oE 'state=[^ ]*' | head -1 | cut -d= -f2-)
    desc=\$(printf '%s' "\$args" | grep -oE 'description=[^ ]*(( [^ ]*)*)' | sed 's/^description=//')
    echo "POST state=\$state description=\$desc" >> "$POSTED_LOG"
    ;;
  *"pr diff"*"--name-only"*)
    echo "some/file.sh"
    ;;
  *"pr diff"*"--stat"*)
    echo "1 file changed"
    ;;
  *)
    exit 0
    ;;
esac
GHSTUB
    chmod +x "$TMP/gh"
}

set_comment_body() {
    printf '%s' "$1" | base64 | tr -d '\n' > "$COMMENT_B64_FILE"
    printf '\n' >> "$COMMENT_B64_FILE"
}

set_statuses() { # json array
    printf '%s' "$1" > "$STATUSES_FILE"
}

run_gate() {
    (
        export PATH="$TMP:$PATH"
        tg_gate_pr "$TEST_PR"
    )
}

# ══════════════════════════════════════════════════════════════════════════
# Test 1: tier-0 artifact, legitimate verdict -> pending then success posted
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=101 TEST_SHA=sha0legit
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
tg_judge() { printf 'legitimate\nLooks honest.\n'; return 0; }
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check "T1: exit reports gated (tier 0, legitimate)" "0" "$?"
check_contains "T1: pending posted before terminal" "state=pending" "$posted"
check_contains "T1: terminal success posted" "state=success" "$posted"
check_contains "T1: success description carries verdict=legitimate" "verdict=legitimate" "$posted"
check_contains "T1: pending posted BEFORE success (ordering)" "$(printf 'POST state=pending')" "$(printf '%s' "$posted" | head -1)"
check_contains "T1: summary line reports tier=0" "tier=0" "$out"

# ══════════════════════════════════════════════════════════════════════════
# Test 2: tier-1/2 artifact -> short-circuit success + verdict=not-tier-0,
# NO judge call, NO pending step (uniform context, no per-tier gymnastics)
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=102 TEST_SHA=sha1
reset_gh_state
write_gh_stub
set_comment_body "$(tier1_body "$TEST_PR" "$TEST_SHA" GO)"
tg_judge() { echo "JUDGE CALLED — should never happen for tier 1/2" >> "$TMP/judge_called.log"; printf 'legitimate\nx\n'; return 0; }
rm -f "$TMP/judge_called.log"
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check "T2: tier-1 artifact short-circuits to success" "0" "$?"
check_contains "T2: posted status is success" "state=success" "$posted"
check_contains "T2: description names not-tier-0" "verdict=not-tier-0" "$posted"
check_not_contains "T2: NO pending status posted for tier-1 short-circuit" "state=pending" "$posted"
[[ -f "$TMP/judge_called.log" ]] && fails=$((fails+1)) && echo "FAIL - T2: judge was called for a tier-1 artifact" || echo "ok   - T2: judge NOT called for tier-1 artifact"

# ══════════════════════════════════════════════════════════════════════════
# Test 3: already-terminal SHA (success already posted) -> no action
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=103 TEST_SHA=sha_terminal
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
set_statuses '[{"state":"success","description":"verdict=legitimate","created_at":"2020-01-01T00:00:00Z"}]'
tg_judge() { echo "JUDGE CALLED" >> "$TMP/judge_called2.log"; printf 'legitimate\nx\n'; return 0; }
rm -f "$TMP/judge_called2.log"
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check "T3: already-terminal SHA -> no new status posted" "" "$posted"
check_contains "T3: summary reports skip" "skip:" "$out"
[[ -f "$TMP/judge_called2.log" ]] && fails=$((fails+1)) && echo "FAIL - T3: judge called on already-terminal SHA" || echo "ok   - T3: judge NOT called (idempotent)"

# ══════════════════════════════════════════════════════════════════════════
# Test 4: stubbed judge rc != 0 -> error (never failure)
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=104 TEST_SHA=sha_judge_fail
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
tg_judge() { printf 'garbage output\n'; return 1; }
out=$(run_gate)
rc=$?
posted=$(cat "$POSTED_LOG")
check "T4: judge rc!=0 -> tg_gate_pr reports failure exit" "1" "$rc"
check_contains "T4: error status posted" "state=error" "$posted"
check_not_contains "T4: never posts state=failure for infra error" "state=failure" "$posted"

# ══════════════════════════════════════════════════════════════════════════
# Test 4b: judge returns illegitimate (rc 0) -> failure, distinct from error
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=104 TEST_SHA=sha_illegit
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
tg_judge() { printf 'illegitimate\nDishonest justification.\n'; return 0; }
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check_contains "T4b: illegitimate verdict posts failure (not error)" "state=failure" "$posted"
check_not_contains "T4b: illegitimate is not posted as error" "state=error" "$posted"

# ══════════════════════════════════════════════════════════════════════════
# Test 5: new SHA on a PR that already has a terminal status for an OLD SHA
# -> re-gates naturally (per-SHA idempotence, not per-PR)
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=105 TEST_SHA=sha_new
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
# statuses list is queried per-SHA (commits/<sha>/statuses) so a stale status
# on a DIFFERENT sha simply never appears here — empty statuses for the new sha.
set_statuses '[]'
tg_judge() { printf 'legitimate\nx\n'; return 0; }
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check_contains "T5: new SHA re-gates (pending posted)" "state=pending" "$posted"
check_contains "T5: new SHA re-gates (terminal success posted)" "state=success" "$posted"

# ══════════════════════════════════════════════════════════════════════════
# Test 6: stale pending (older than TTL) -> reclaimed (re-gated)
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=106 TEST_SHA=sha_stale
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
old_ts=$(date -u -v-1H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '-1 hour' +%Y-%m-%dT%H:%M:%SZ)
set_statuses "[{\"state\":\"pending\",\"description\":\"verdict=pending\",\"created_at\":\"$old_ts\"}]"
tg_judge() { printf 'legitimate\nx\n'; return 0; }
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check_contains "T6: stale pending is reclaimed (new pending posted)" "state=pending" "$posted"
check_contains "T6: stale pending is reclaimed (terminal posted)" "state=success" "$posted"

# ══════════════════════════════════════════════════════════════════════════
# Test 7 (negative control for T6 — SO-31): a FRESH pending (well within TTL)
# is NOT reclaimed. A buggy runner that ignores TTL and always reclaims would
# pass T6 but fail this — this is the test that actually proves the TTL
# boundary discriminates, not just that reclaim exists at all.
# ══════════════════════════════════════════════════════════════════════════
TEST_PR=107 TEST_SHA=sha_fresh_pending
reset_gh_state
write_gh_stub
set_comment_body "$(tier0_body "$TEST_PR" "$TEST_SHA" GO)"
fresh_ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
set_statuses "[{\"state\":\"pending\",\"description\":\"verdict=pending\",\"created_at\":\"$fresh_ts\"}]"
tg_judge() { echo "JUDGE CALLED" >> "$TMP/judge_called3.log"; printf 'legitimate\nx\n'; return 0; }
rm -f "$TMP/judge_called3.log"
out=$(run_gate)
posted=$(cat "$POSTED_LOG")
check "T7: fresh pending -> no new status posted (not reclaimed)" "" "$posted"
check_contains "T7: summary reports skip for fresh pending" "skip:" "$out"
[[ -f "$TMP/judge_called3.log" ]] && fails=$((fails+1)) && echo "FAIL - T7: judge called despite fresh (non-stale) pending" || echo "ok   - T7: judge NOT called for fresh pending"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
