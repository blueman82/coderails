#!/bin/bash
# shellcheck disable=SC1090,SC2015 # Test fixture sources a computed path and uses the suite's existing final tally idiom.
# Behavioural test for loop_dispatch_guard.sh — the PreToolUse:Agent gate that
# mirrors loop_state_guard.sh's work-unit-count + loop-scope-evals check, but
# fires at DISPATCH time (before a coderails:loop-worker Agent call) instead
# of at loop completion. Helper conventions copied verbatim (in spirit) from
# loop_state_guard_evals.test.sh, per this repo's "bash test files are
# self-contained" pattern.
#
# work_units is a PLAN-TIME roster (loop-state.md's Fields table: entries
# exist with status "pending" BEFORE any dispatch) — fixtures below use
# "pending" for pre-dispatch state, never "done" (a post-dispatch status a
# pre-dispatch fixture cannot honestly claim).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
GUARD="$HERE/../loop_dispatch_guard.sh"
POST_EVALS="$HERE/../../../scripts/post_evals.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1
fails=0
check() { # desc expected actual
    if [ "$2" = "$3" ]; then
        printf 'ok   - %s\n' "$1"
    else
        printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"
        fails=$((fails + 1))
    fi
}

stamp() { (
    source "$POST_EVALS" >/dev/null 2>&1
    post_evals::grade_loop "$1" >/dev/null
) || {
    printf 'stamp: grade_loop refused %s\n' "$1" >&2
    return 1
}; }

CWD="/work/project"
SLUG="-work-project"
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }
file_path() { printf '%s/progress.json' "$(file_dir "$1")"; }

# write_file: session_id [work_units_json] [status]
write_file() {
    local session="$1" wu="${2:-{\}}" status="${3:-in-progress}"
    local dir
    dir=$(file_dir "$session")
    mkdir -p "$dir"
    jq -n --arg session "$session" --arg status "$status" --argjson wu "$wu" \
        '{schema_version:1, status:$status, session_id:$session, completed_marker:0, work_units:$wu}' \
        >"$dir/progress.json"
}

# payload: session_id subagent_type
payload() {
    printf '{"tool_name":"Agent","tool_input":{"subagent_type":"%s"},"session_id":"%s","cwd":"%s"}' \
        "$2" "$1" "$CWD"
}

run() { echo "$1" | bash "$GUARD"; } # -> stdout (JSON block, or empty on allow)
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

is_denied() { # stdout_json -> 0 if permissionDecision=deny, 1 otherwise
    printf '%s' "$1" | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null 2>&1
}

WU1_PENDING='{"wu1":{"status":"pending"}}'
WU2_PENDING='{"wu1":{"status":"pending"},"wu2":{"status":"pending"}}'
WU3_PENDING='{"wu1":{"status":"pending"},"wu2":{"status":"pending"},"wu3":{"status":"pending"}}'
WU5_PENDING='{"wu1":{"status":"pending"},"wu2":{"status":"pending"},"wu3":{"status":"pending"},"wu4":{"status":"pending"},"wu5":{"status":"pending"}}'

# ── Non-Agent tool call -> always allow, no matter the state ────────────────
# Carries a STRAY subagent_type key on a Bash call, so this exercises the
# tool_name=="Agent" filter specifically — deleting that filter would let a
# non-Agent call with this key fall through to the roster check below and
# wrongly deny, which this assertion would then catch.
reset
write_file S1 "$WU3_PENDING"
out=$(echo '{"tool_name":"Bash","tool_input":{"command":"ls","subagent_type":"coderails:loop-worker"},"session_id":"S1","cwd":"'"$CWD"'"}' | bash "$GUARD")
check "non-Agent tool call (stray subagent_type key) -> allow (empty stdout)" "" "$out"

# ── No progress.json at all -> block (dispatch requires owned loop state) ───
reset
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "no progress.json -> BLOCK" 0 $?

# ── Non-implementation-unit subagent_type -> always allow, regardless of count
reset
write_file S1 "$WU3_PENDING"
out=$(run "$(payload S1 coderails:preflight-scout)")
check "non-implementation-unit subagent_type, 3-unit roster, no evals.json -> allow" "" "$out"

# ── Session mismatch -> block (foreign state cannot authorize dispatch) ─────
reset
write_file OTHER "$WU3_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "session mismatch (progress.json owned by OTHER, dispatch is S1) -> BLOCK" 0 $?

# ── Below threshold: 1-unit roster, all pending, no evals.json -> allow ─────
reset
write_file S1 "$WU1_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
check "1-unit roster (all pending), no evals.json -> allow (below threshold)" "" "$out"

# ── Below threshold: 2-unit roster, all pending, no evals.json -> allow ─────
reset
write_file S1 "$WU2_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
check "2-unit roster (all pending), no evals.json -> allow (below threshold)" "" "$out"

# ── At threshold: 3-unit roster, ALL PENDING (nothing dispatched yet), no
# evals.json -> BLOCK on the FIRST implementation-unit dispatch. This is the
# core regression case: roster size alone (not a dispatch ordinal) decides
# whether Phase 2.7 applies, so the very first dispatch of a >=3-unit loop is
# gated exactly like its third. ─────────────────────────────────────────────
reset
write_file S1 "$WU3_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "3-unit roster ALL PENDING (first dispatch), no evals.json -> BLOCK" 0 $?
case "$out" in
*"evals.json"*"Phase 2.7c"*) : ;;
*)
    fails=$((fails + 1))
    printf 'FAIL - deny reason missing evals.json/Phase 2.7c mention: %s\n' "$out"
    ;;
esac

# ── At threshold, evals.json present, GO, justified, STAMPED -> allow ───────
reset
write_file S1 "$WU3_PENDING"
jq -n '{scope:"loop", verification_level:1, verification_justification:"3 work-units, no irreversible surface", head_sha:"deadbeef", evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "3-unit roster, GO evals justified+stamped -> allow" "" "$out"

# ── At threshold, evals.json present, VERIFICATION_LEVEL0, justified, STAMPED -> allow
reset
write_file S1 "$WU3_PENDING"
jq -n '{scope:"loop", verification_level:0, verification_justification:"docs-only loop, no runtime behaviour", head_sha:"deadbeef", evals:[]}' >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "3-unit roster, VERIFICATION_LEVEL0 justified+stamped -> allow" "" "$out"

# ── At threshold, evals.json NO-GO -> BLOCK ─────────────────────────────────
reset
write_file S1 "$WU3_PENDING"
jq -n '{scope:"loop", result:"NO-GO", verification_level:1, verification_justification:"3 work-units, no irreversible surface"}' >"$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "3-unit roster, NO-GO evals -> BLOCK" 0 $?

# ── At threshold, evals.json GO but UNJUSTIFIED -> BLOCK ────────────────────
reset
write_file S1 "$WU3_PENDING"
jq -n '{scope:"loop", result:"GO", verification_level:1, verification_justification:""}' >"$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "3-unit roster, GO but unjustified evals -> BLOCK" 0 $?

# ── At threshold, evals.json hand-written GO, never stamped -> BLOCK (UNSTAMPED)
reset
write_file S1 "$WU3_PENDING"
jq -n '{scope:"loop", result:"GO", verification_level:1, verification_justification:"hand-written, never graded"}' >"$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "3-unit roster, hand-written GO never stamped -> BLOCK (UNSTAMPED)" 0 $?

# ── Well above threshold: 5-unit roster, all pending, no evals.json -> BLOCK
reset
write_file S1 "$WU5_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "5-unit roster (all pending), no evals.json -> BLOCK" 0 $?

# ── A stale evals.json from a prior loop cannot authorise a re-armed graph. ──
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new",revision:0,graph:{nodes:{},edges:[],joins:{}}}' \
    "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
jq -n '{scope:"loop",session_id:"S1",loop_id:"loop-old",revision:7,verification_level:1,verification_justification:"prior loop, 3 work-units",head_sha:"deadbeef",evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "stale same-session evals.json from a prior loop -> BLOCK" 0 $?

# ── Every graph record needs stable loop identity before dispatch. ───────────
reset
write_file S1 "$WU3_PENDING"
jq '. + {graph:{nodes:{},edges:[],joins:{}},revision:0}' \
    "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "graph state missing loop_id -> BLOCK" 0 $?

reset
write_file S1 "$WU3_PENDING"
jq '. + {graph:{nodes:{},edges:[],joins:{}},loop_id:"loop-new"}' \
    "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "graph state missing revision -> BLOCK" 0 $?

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
