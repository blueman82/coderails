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

# Tests T1-T7 above each redefine tg_judge in this top-level shell (not a
# subshell), so the LAST redefinition (T7's) is still active here. Undefine
# it and re-source the runner so the tests below exercise the REAL tg_judge
# implementation, not a leftover per-test stub.
unset -f tg_judge
source "$RUNNER"

# ══════════════════════════════════════════════════════════════════════════
# Task 3: tg_judge — blind judge via direct Anthropic API (real implementation,
# NOT redefined here). Stubs `curl` on PATH and points TIER_GATE_CREDS at a
# fixture credentials file; never a real network call.
# ══════════════════════════════════════════════════════════════════════════
CREDS_FILE="$TMP/creds"
CURL_CALLS="$TMP/curl_calls.log"
CURL_RESPONSES="$TMP/curl_responses"  # one file per call, read in order

write_creds() { # <anthropic_key>
    printf 'ANTHROPIC_API_KEY=%s\n' "$1" > "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"
}

# write_curl_stub <response1> [response2 ...]
# Each call to `curl` echoes the next response body in order and appends a
# call-count line to CURL_CALLS so tests can assert exactly-once / exactly-N.
# Paths are interpolated directly (no heredoc+sed dance) to avoid quoting
# fights with embedded JSON in the response bodies.
write_curl_stub() {
    rm -rf "$CURL_RESPONSES"; mkdir -p "$CURL_RESPONSES"
    local i=1
    for resp in "$@"; do
        printf '%s' "$resp" > "$CURL_RESPONSES/$i"
        i=$((i+1))
    done
    {
        printf '#!/bin/bash\n'
        printf 'COUNT_FILE=%q\n' "$CURL_CALLS"
        printf 'RESP_DIR=%q\n' "$CURL_RESPONSES"
        printf 'n=$(( $(wc -l < "$COUNT_FILE" 2>/dev/null || echo 0) + 1 ))\n'
        printf 'echo "call $n" >> "$COUNT_FILE"\n'
        printf 'resp_file="$RESP_DIR/$n"\n'
        printf 'if [[ -f "$resp_file" ]]; then\n'
        printf '    cat "$resp_file"\n'
        printf 'else\n'
        printf '    last=$(ls "$RESP_DIR" | sort -n | tail -1)\n'
        printf '    cat "$RESP_DIR/$last"\n'
        printf 'fi\n'
    } > "$TMP/curl"
    chmod +x "$TMP/curl"
}

# write_hanging_curl_stub — never returns (used for watchdog test)
write_hanging_curl_stub() {
    {
        printf '#!/bin/bash\n'
        printf 'COUNT_FILE=%q\n' "$CURL_CALLS"
        printf 'echo "call" >> "$COUNT_FILE"\n'
        printf 'sleep 999\n'
    } > "$TMP/curl"
    chmod +x "$TMP/curl"
}

# anthropic_success_body <verdict> <reason>
# A minimal Messages API response whose content[0].text is the strict-JSON
# {verdict, reason} contract tg_judge parses.
anthropic_success_body() {
    local verdict="$1" reason="$2"
    printf '{"content":[{"type":"text","text":"{\\"verdict\\":\\"%s\\",\\"reason\\":\\"%s\\"}"}],"stop_reason":"end_turn"}' \
        "$verdict" "$reason"
}

run_judge() { # evals_json filelist diffstat
    (
        export PATH="$TMP:$PATH"
        export TIER_GATE_CREDS="$CREDS_FILE"
        export TIER_GATE_WATCHDOG_TIMEOUT=2
        tg_judge "$1" "$2" "$3"
    )
}

# run_judge_with_stderr — same as run_judge but merges stderr into stdout, for
# tests asserting on tg_judge's named-error text (which goes to stderr by the
# runner's own convention — see tg_gate_pr's other error paths).
run_judge_with_stderr() { # evals_json filelist diffstat
    (
        export PATH="$TMP:$PATH"
        export TIER_GATE_CREDS="$CREDS_FILE"
        export TIER_GATE_WATCHDOG_TIMEOUT=2
        tg_judge "$1" "$2" "$3" 2>&1
    )
}

FIXTURE_EVALS='{"tier":0,"tier_justification":"x","evals":[]}'
FIXTURE_FILES="scripts/foo.sh"
FIXTURE_DIFFSTAT=" 1 file changed, 3 insertions(+)"

# ── Test J1: legitimate verdict -> stdout "legitimate\n<reason>", rc 0 ───────
: > "$CURL_CALLS"
write_creds "sk-ant-fixture-key"
write_curl_stub "$(anthropic_success_body legitimate "Matches the task scope.")"
out=$(run_judge "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
check "J1: tg_judge rc 0 on legitimate parse" "0" "$rc"
check "J1: line 1 is bare 'legitimate' (no prefix, no JSON)" "legitimate" "$(printf '%s' "$out" | head -1 | tr -d '[:space:]')"
check_contains "J1: reason follows on subsequent line(s)" "Matches the task scope" "$out"
check "J1: curl invoked exactly once" "1" "$(wc -l < "$CURL_CALLS" | tr -d ' ')"

# ── Test J2: illegitimate verdict -> stdout "illegitimate\n<reason>", rc 0 ──
: > "$CURL_CALLS"
write_curl_stub "$(anthropic_success_body illegitimate "Claim contradicts the diff.")"
out=$(run_judge "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
check "J2: tg_judge rc 0 on illegitimate parse" "0" "$rc"
check "J2: line 1 is bare 'illegitimate'" "illegitimate" "$(printf '%s' "$out" | head -1 | tr -d '[:space:]')"
check_contains "J2: reason present" "contradicts" "$out"

# ── Test J3: insufficient verdict -> stdout "insufficient\n<reason>", rc 0 ──
: > "$CURL_CALLS"
write_curl_stub "$(anthropic_success_body insufficient "Not enough evidence in the blind inputs.")"
out=$(run_judge "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
check "J3: tg_judge rc 0 on insufficient parse" "0" "$rc"
check "J3: line 1 is bare 'insufficient'" "insufficient" "$(printf '%s' "$out" | head -1 | tr -d '[:space:]')"

# ── Test J4: malformed response -> retry once -> still malformed -> rc 1 ───
: > "$CURL_CALLS"
write_curl_stub 'not json at all' 'still not json'
out=$(run_judge "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
check "J4: malformed response after retry -> rc 1" "1" "$rc"
check "J4: exactly one retry (2 curl calls total)" "2" "$(wc -l < "$CURL_CALLS" | tr -d ' ')"

# ── Test J5 (negative control for J4 — SO-31 pairing, mirrors T6/T7):
#    a WELL-FORMED response must invoke curl exactly ONCE. Proves the retry
#    in J4 is conditional on failure, not an unconditional double-call that
#    would vacuously "pass" J4 too. ───────────────────────────────────────
: > "$CURL_CALLS"
write_curl_stub "$(anthropic_success_body legitimate "fine")"
run_judge "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT" >/dev/null
check "J5: well-formed response -> curl called exactly once (not retried)" "1" "$(wc -l < "$CURL_CALLS" | tr -d ' ')"

# ── Test J6: missing creds file -> rc 1 with a NAMED error (not generic) ───
# The named error goes to stderr (this runner's own convention for tg_judge's
# other failure messages) — use run_judge_with_stderr to assert on it.
: > "$CURL_CALLS"
rm -f "$CREDS_FILE"
write_curl_stub "$(anthropic_success_body legitimate "unreachable")"
out=$(run_judge_with_stderr "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
check "J6: missing creds file -> rc 1" "1" "$rc"
check_contains "J6: error names the missing-creds cause" "TIER_GATE_CREDS" "$out"
check "J6: curl never invoked (fails before network call)" "0" "$(wc -l < "$CURL_CALLS" 2>/dev/null | tr -d ' ' || echo 0)"
write_creds "sk-ant-fixture-key"  # restore for subsequent tests

# ── Test J7: creds file present but missing the ANTHROPIC_API_KEY line ─────
: > "$CURL_CALLS"
: > "$CREDS_FILE"  # empty file, key absent
out=$(run_judge_with_stderr "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
check "J7: creds file present but key absent -> rc 1" "1" "$rc"
check_contains "J7: error names the missing-key cause" "ANTHROPIC_API_KEY" "$out"
write_creds "sk-ant-fixture-key"

# ── Test J8: watchdog timeout on a hung curl call -> rc 1 (never hangs) ────
: > "$CURL_CALLS"
write_hanging_curl_stub
start_ts=$(date +%s)
out=$(run_judge "$FIXTURE_EVALS" "$FIXTURE_FILES" "$FIXTURE_DIFFSTAT")
rc=$?
end_ts=$(date +%s)
elapsed=$((end_ts - start_ts))
check "J8: hung API call -> tg_judge rc 1 (never hangs the daemon)" "1" "$rc"
# Watchdog timeout is 2s (env override above); one retry means worst case is
# bounded at ~2x timeout. Generous upper bound (20s) avoids flaking on a slow
# CI runner while still proving the call does NOT block indefinitely.
[[ $elapsed -lt 20 ]] && echo "ok   - J8: bounded wall-clock (${elapsed}s < 20s, not an indefinite hang)" \
    || { echo "FAIL - J8: wall-clock ${elapsed}s exceeded bound — watchdog not wired to the judge call"; fails=$((fails+1)); }

# ── Test J9: never references the claude CLI (spec's central constraint) ──
# grep -c exits 1 on zero matches (still printing "0" to stdout) — capture
# stdout only, ignore exit status, so the count is never corrupted.
cli_refs="$(grep -c "claude --print\|claude -p" "$REPO_ROOT/scripts/tier-gate/tier-gate-runner.sh" 2>/dev/null)"
[[ -z "$cli_refs" ]] && cli_refs=0
check "J9: tier-gate-runner.sh never shells out to the claude CLI" "0" "$cli_refs"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
