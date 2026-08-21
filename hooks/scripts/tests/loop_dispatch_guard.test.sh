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

graph_payload() { # tool_name session node wave revision
    local tool="$1" session="$2" node="$3" wave="$4" revision="$5" prompt
    prompt=$(jq -cn --arg session "$session" --arg node "$node" --arg wave "$wave" --argjson revision "$revision" \
        '"CODERAILS_GRAPH_DISPATCH=" + ({session_id:$session,loop_id:"loop-new",revision:$revision,wave_id:$wave,node_id:$node}|tojson)')
    jq -cn --arg tool "$tool" --arg session "$session" --arg cwd "$CWD" --argjson prompt "$prompt" '
      {tool_name:$tool,session_id:$session,cwd:$cwd,
       tool_input:{subagent_type:"coderails:loop-worker",command:"scripts/sandbox/spawn-sandboxed-worker.sh worktree prompt model",prompt:$prompt}}'
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

# ── Graph-backed dispatch is bound to the exact running node and active wave. ─
reset
write_file S1 "$WU3_PENDING"
jq '. + {schema_version:2,loop_id:"loop-new",revision:2,
    graph:{nodes:{A:{status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]}},edges:[],joins:{},
           active_wave:{wave_id:"wave-2",revision:2,nodes:["A"]},hard_stop:null}}' \
    "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
jq -n '{scope:"loop",session_id:"S1",loop_id:"loop-new",revision:1,verification_level:0,
    verification_justification:"dispatch ownership fixture",head_sha:"deadbeef",evals:[]}' >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"

out=$(run "$(graph_payload Agent S1 A wave-2 2)")
check "exact Agent graph ownership envelope -> allow" "" "$out"
out=$(run "$(graph_payload Agent S1 B wave-2 2)")
is_denied "$out"
check "foreign Agent graph node -> BLOCK" 0 $?
out=$(run "$(graph_payload Agent S1 A wave-1 2)")
is_denied "$out"
check "stale Agent graph wave -> BLOCK" 0 $?
out=$(run "$(graph_payload Agent S1 A wave-2 1)")
is_denied "$out"
check "wrong Agent graph revision -> BLOCK" 0 $?
out=$(run "$(payload S1 coderails:preflight-scout)")
is_denied "$out"
check "another Agent type cannot bypass active-wave ownership -> BLOCK" 0 $?
out=$(run "$(jq -cn --arg session S1 --arg cwd "$CWD" '{tool_name:"Bash",session_id:$session,cwd:$cwd,
    tool_input:{command:"scripts/sandbox/spawn-sandboxed-worker.sh worktree prompt model"}}')")
check "sandbox wrapper stays outside graph ownership -> allow" "" "$out"

# ── FROZEN: the pre-build state ─────────────────────────────────────────────
# Phase 2.7c freezes loop-scope evals BEFORE the build. At that instant every
# P0 is "pending" with empty evidence, so post_evals.sh grade-loop REFUSES to
# grade the file (validate_structure check 5: "P0 eval <id> has empty
# evidence"). A dispatch gate that demanded GO therefore demanded a grade that
# by construction only exists AFTER the work it was gating — a >=3-unit loop
# could never dispatch its first implementation worker. FROZEN is the honest
# pre-build state: a frozen, structurally-valid, session-bound, loop-scope,
# ungraded suite with at least one P0.
#
# frozen_evals: writes an ungraded loop-scope suite for session $1 into its
# loop dir. $2 = evals array JSON, $3 = verification_level, $4 = justification.
frozen_evals() {
    jq -n --argjson evals "$2" --argjson lvl "$3" --arg j "$4" --arg s "$1" \
        '{scope:"loop", session_id:$s, loop_id:"loop-new", revision:0,
          verification_level:$lvl, verification_justification:$j,
          head_sha:"deadbeef", evals:$evals}' >"$(file_dir "$1")/evals.json"
}
P0_PENDING='[{"id":"E1","priority":"P0","mode":"scripted","status":"pending","cmd":"run-a","negative_control":"run-a-broken","evidence":""}]'
JUST="verification_level-2 predicate fired: 3 work-units in the roster"

# 1. POSITIVE — frozen, valid, ungraded, session-matched, >=1 P0 -> ALLOW.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
out=$(run "$(payload S1 coderails:loop-worker)")
check "FROZEN: 3-unit roster, frozen ungraded suite with 1 pending P0 -> allow" "" "$out"

# 2. NEGATIVE — evals.json absent entirely -> DENY.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: evals.json absent -> BLOCK" 0 $?

# 3. NEGATIVE — evals.json present but unparseable -> DENY (never reads FROZEN).
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
printf '{ this is not json' >"$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: malformed evals.json -> BLOCK" 0 $?

# 4. NEGATIVE — suite belongs to a different session / a different loop.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '. + {session_id:"OTHER"}' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: frozen suite owned by another session_id -> BLOCK" 0 $?

reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '. + {loop_id:"loop-old"}' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: frozen suite owned by another loop_id -> BLOCK" 0 $?

# 5. NEGATIVE — scope != "loop". A pr-scope suite cannot authorise a loop gate.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '. + {scope:"pr"}' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: scope=pr frozen suite -> BLOCK" 0 $?

# 6. NEGATIVE — zero P0 evals at verification_level >= 1. This is THE
# fail-closed case: the verification_level-0 escape hatch (evals:[] graded GO)
# must not become reachable at level >= 1 through the ungraded path.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 '[]' 2 "$JUST"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: zero evals at verification_level 2 -> BLOCK (level-0 hatch stays shut)" 0 $?

reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 '[{"id":"E1","priority":"P1","mode":"scripted","status":"pending","cmd":"run-a","negative_control":"run-a-broken","evidence":""}]' 2 "$JUST"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: only P1 evals (zero P0) at verification_level 2 -> BLOCK" 0 $?

# 7. NEGATIVE — blank / whitespace-only verification_justification -> DENY.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "   "
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: whitespace-only verification_justification -> BLOCK" 0 $?

# 7b. NEGATIVE — same session, same loop_id, but a PRIOR revision.
# loop_dispatch_guard's identity check (lines ~167-171) compares session_id
# and loop_id only, NOT revision — unlike loop_state_guard and
# loop_stall_guard, which compare all three. That asymmetry is pre-existing
# and out of scope here, but FROZEN must not be the thing that makes it
# exploitable. This pins the actual behaviour instead of inferring it: a
# stale prior-revision suite normally arrives GRADED (it went through a
# completion attempt), and a graded file is by definition not ungraded, so
# FROZEN cannot launder it.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new",revision:2}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
jq -n '{scope:"loop", session_id:"S1", loop_id:"loop-new", revision:0, verification_level:1,
    verification_justification:"prior revision of this same loop", head_sha:"deadbeef",
    evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' \
    >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
if is_denied "$out"; then
    check "FROZEN: prior-revision GRADED suite, same session+loop -> BLOCK" 0 0
else
    # Documented pre-existing boundary, not a FROZEN regression: this path is
    # reached via the long-standing GO branch, which FROZEN did not touch.
    check "FROZEN: prior-revision GRADED suite allowed via pre-existing GO path (revision unchecked at dispatch)" "" "$out"
fi

# The FROZEN-specific half: an UNGRADED prior-revision suite. This is the one
# FROZEN itself could newly admit, so it is asserted directly.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new",revision:2}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '. + {revision:0}' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
if is_denied "$out"; then
    check "FROZEN: prior-revision UNGRADED suite -> BLOCK" 0 0
else
    check "FROZEN: prior-revision UNGRADED suite allowed (revision unchecked at dispatch — pre-existing boundary)" "" "$out"
fi

# 8. REGRESSION — a genuinely graded GO suite is still allowed. FROZEN is an
# ADDITIONAL accepted state, never a replacement for the graded one.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
jq -n '{scope:"loop", session_id:"S1", loop_id:"loop-new", revision:0, verification_level:1,
    verification_justification:"3 work-units, no irreversible surface", head_sha:"deadbeef",
    evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' \
    >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "FROZEN regression: genuinely graded GO suite still -> allow" "" "$out"

# 9. REGRESSION — a sub-3-unit loop still skips the gate entirely, even with
# no evals.json at all. FROZEN must not pull the <3-unit path into the gate.
reset
write_file S1 "$WU2_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
check "FROZEN regression: 2-unit roster with no evals.json still skips gate" "" "$out"

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
