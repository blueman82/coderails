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

WU0_PENDING='{}'
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

# ── Below threshold: 0-unit roster, no evals.json -> allow ──────────────────
reset
write_file S1 "$WU0_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
check "0-unit roster, no evals.json -> allow (below threshold)" "" "$out"

# ── Above threshold: 3-unit roster, ALL PENDING (nothing dispatched yet), no
# evals.json -> BLOCK on the FIRST implementation-unit dispatch. This is the
# core regression case: roster size alone (not a dispatch ordinal) decides
# whether Phase 2.7 applies, so the very first dispatch of a >=1-unit loop is
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
# Emits the field set a REAL /coderails:task-evals freeze produces, including
# frozen_sha/frozen_at. A helper that omitted them would make every negative
# case below pass for the WRONG reason (denied on a missing frozen_sha rather
# than on the property the test is named for). head_sha is deliberately null:
# the live suite carries null there, because head_sha records which commit was
# GRADED and at freeze time nothing has been.
frozen_evals() {
    jq -n --argjson evals "$2" --argjson lvl "$3" --arg j "$4" --arg s "$1" \
        '{schema_version:1, scope:"loop", session_id:$s, loop_id:"loop-new", revision:0,
          verification_level:$lvl, verification_justification:$j,
          frozen_at:"2026-08-21T00:00:00Z", frozen_sha:"aaaabbbbcccc",
          head_sha:null, amendments:[], result:null, grading:null, evals:$evals}' \
        >"$(file_dir "$1")/evals.json"
}
P0_PENDING='[{"id":"E1","priority":"P0","mode":"scripted","status":"pending","cmd":"bash run-a.sh","negative_control":"bash run-a-broken.sh","evidence":""}]'
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
# NOTE ON WHAT THIS ACTUALLY GUARDS: als_evals_are_frozen has no
# justification clause, and the reader's UNJUSTIFIED branch fires BEFORE the
# FROZEN branch in the if-chain. So this pins BRANCH ORDER, not the
# predicate: the file below satisfies als_evals_are_frozen outright, and only
# the earlier UNJUSTIFIED branch stops it. Reversing that order would open
# the gate to unjustified suites, which is why the case stays.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "   "
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: whitespace-only verification_justification -> BLOCK" 0 $?

# 7b. Prior revision, same session + same loop_id -> ALLOW, deterministically.
# This is DESIGNED behaviour, not a tolerated boundary. loop-state.md:77:
# "Dispatch evidence binds the stable session_id + loop_id, not revision,
# because beginning a wave advances the revision before dispatch. Completion
# evidence binds all three values."
#
# Binding revision at dispatch would re-create the very deadlock this PR
# fixes, in a new form: every wave start bumps the revision, so a suite frozen
# once at Phase 2.7c would invalidate itself on the first wave. Both halves
# below assert ALLOW outright — an earlier revision of this file used an
# if/else where BOTH branches called check() with a passing expectation, which
# recorded whatever the code did as acceptable and could never fail.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new",revision:2}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
jq -n '{scope:"loop", session_id:"S1", loop_id:"loop-new", revision:0, verification_level:1,
    verification_justification:"prior revision of this same loop", head_sha:"deadbeef",
    evals:[{id:"e1",priority:"P0",mode:"scripted",status:"pass",cmd:"run-a",negative_control:"run-a-broken",evidence:"log"}]}' \
    >"$(file_dir S1)/evals.json"
stamp "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "prior-revision GRADED suite, same session+loop -> allow (loop-state.md:77)" "" "$out"

reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new",revision:2}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '. + {revision:0}' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "prior-revision FROZEN suite, same session+loop -> allow (loop-state.md:77)" "" "$out"

# 7c. The hollow-file forgery, pinned to the LITERAL shape found in review.
# Six hand-typed keys, one eval carrying nothing but a priority: no id, mode,
# cmd, negative_control, status, frozen_sha, head_sha or schema_version. This
# passed an earlier revision of the FROZEN predicate and opened the dispatch
# gate. The predicate floor is now validate_structure's freeze-time-satisfiable
# subset, so a shape the project's own eval validator rejects cannot open it.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
printf '%s' '{"scope":"loop","session_id":"S1","loop_id":"loop-new","verification_level":2,"verification_justification":"x","evals":[{"priority":"P0"}]}' >"$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: hollow 6-key hand-typed file -> BLOCK (forgery floor)" 0 $?

# 7d. Per-field forgery floor. Each case starts from a REAL frozen suite and
# removes exactly ONE field, so each asserts its own named property rather
# than tripping over a shared missing field.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq 'del(.frozen_sha)' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: frozen_sha absent -> BLOCK (no freeze-before-build evidence)" 0 $?

reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '.evals[0].mode = "handwave"' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: unrecognised eval mode -> BLOCK" 0 $?

reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '.evals[0].negative_control = "   "' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: scripted eval with blank negative_control -> BLOCK" 0 $?

# An `agent-run` eval legitimately carries no cmd/negative_control (validator
# check 3 scopes its demand to scripted evals, and the live suite has exactly
# this shape). Guards against overtightening that would deny the real path.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 '[{"id":"E1","priority":"P0","mode":"agent-run","status":"pending","cmd":"","negative_control":"","evidence":""}]' 2 "$JUST"
out=$(run "$(payload S1 coderails:loop-worker)")
check "FROZEN: agent-run P0 with empty cmd/negative_control -> allow (matches live suite)" "" "$out"

# 7e. Ownership: a blank loop_id must NOT short-circuit the ownership check.
# Previously `[ -n "$loop_id" ] && ...` meant a blank loop_id skipped
# ownership entirely, so a leftover suite owned by a different session AND a
# different loop authorised dispatch. loop_dir is keyed per SESSION, not per
# loop, so a stale file in the same directory is the realistic case.
reset
write_file S1 "$WU3_PENDING"   # no loop_id, no graph -> blank loop_id at the check
jq -n '{scope:"loop", session_id:"A-DIFFERENT-SESSION", loop_id:"a-different-loop",
    verification_level:2, verification_justification:"leftover from an earlier loop",
    frozen_sha:"aaaabbbbcccc", result:null, grading:null,
    evals:[{id:"E1",priority:"P0",mode:"scripted",status:"pending",cmd:"bash run-a.sh",negative_control:"bash run-a-broken.sh",evidence:""}]}' \
    >"$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: blank loop_id cannot skip the ownership check -> BLOCK" 0 $?
case "$out" in
*STALE*) : ;;
*)
    fails=$((fails + 1))
    printf 'FAIL - blank loop_id + foreign session should deny as STALE, got: %s\n' "$out"
    ;;
esac

# The other side of that fix: a blank loop_id is a legacy non-graph loop, NOT
# by itself an ownership violation. When the suite belongs to THIS session it
# must still dispatch — denying wholesale would break a legitimately graded
# GO in such a loop. (Covered for the graded case by the GO/LEVEL0 fixtures
# above, which have no loop_id; asserted here for the FROZEN path.)
reset
write_file S1 "$WU3_PENDING"   # no loop_id, no graph
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq 'del(.loop_id)' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
check "FROZEN: blank loop_id, suite owned by THIS session -> allow (legacy non-graph loop)" "" "$out"

# 7f. The UNGRADED discriminator, at dispatch level. `(.result == null) and
# (.grading == null)` is the clause that DEFINES this state — mutation
# testing found it caught by a single reader test with the whole dispatch
# suite staying green. A partially-graded file must not open the gate: if
# either field is present the suite is not ungraded, whatever else it looks
# like.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '.grading = {by:"post_evals.sh grade-loop", checksum:"deadbeef"}' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: .grading present (not ungraded) -> BLOCK" 0 $?

reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '.result = "GO"' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: .result set without a grading stamp -> BLOCK (UNSTAMPED, never FROZEN)" 0 $?

# 7g. The NUMERIC verification_level guard, at dispatch level. Also caught by
# only one reader test under mutation. A JSON string "2" must not satisfy
# `>= 1` via coercion — otherwise a hand-typed file picks its own level.
reset
write_file S1 "$WU3_PENDING"
jq '. + {loop_id:"loop-new"}' "$(file_path S1)" >"$(file_path S1).tmp" && mv "$(file_path S1).tmp" "$(file_path S1)"
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
jq '.verification_level = "2"' "$(file_dir S1)/evals.json" >"$(file_dir S1)/e.tmp" && mv "$(file_dir S1)/e.tmp" "$(file_dir S1)/evals.json"
out=$(run "$(payload S1 coderails:loop-worker)")
is_denied "$out"
check "FROZEN: verification_level is the STRING \"2\" -> BLOCK (no coercion)" 0 $?

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

# 9. REGRESSION — a sub-1-unit (0-unit) loop still skips the gate entirely,
# even with no evals.json at all. FROZEN must not pull the <1-unit path into
# the gate.
reset
write_file S1 "$WU0_PENDING"
out=$(run "$(payload S1 coderails:loop-worker)")
check "FROZEN regression: 0-unit roster with no evals.json still skips gate" "" "$out"

# ── Graph-owned dispatch of ANY subagent_type is gated on evals ─────────────
# graph_dispatch.sh's role table maps only ONE of six node roles to
# coderails:loop-worker (S2 -> preflight-scout, S2.7e -> proof-author,
# S9-wiki -> wiki-writer, S9-docs -> docs-auditor, U3 -> loop-worker). Gating
# on subagent_type therefore left five roles able to build before the freeze.
# A dispatch is gate-eligible when it carries a validated
# CODERAILS_GRAPH_DISPATCH envelope owning a running node in the active wave.
#
# EXEMPTION RULE: gate-eligibility is keyed on the NODE ID, never the
# subagent_type. Nodes at or before the J2.8 freeze join (S-*, S0*, S1, S2*,
# J2*) author the very evals a downstream node is gated on, so they are
# exempt; everything else (U*, S9-*, S13-*, J12-*, and any unrecognised id)
# is gated. Unknown ids land in the GATED bucket deliberately: a new
# downstream node then fails closed, and a new pre-freeze node blocks loudly
# until the list is updated, which is the safe failure direction for a gate
# this repo has a history of shipping fail-OPEN.
#
# graph_state: writes graph loop state whose active wave holds $2 as running.
graph_state() { # session node
    write_file "$1" "$WU3_PENDING"
    jq --arg n "$2" '. + {schema_version:2,loop_id:"loop-new",revision:2,
        graph:{nodes:{($n):{status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]}},
               edges:[],joins:{},active_wave:{wave_id:"wave-2",revision:2,nodes:[$n]},hard_stop:null}}' \
        "$(file_path "$1")" >"$(file_path "$1").tmp" && mv "$(file_path "$1").tmp" "$(file_path "$1")"
}

# typed_graph_payload: session node subagent_type
typed_graph_payload() {
    local prompt
    prompt=$(jq -cn --arg session "$1" --arg node "$2" \
        '"CODERAILS_GRAPH_DISPATCH=" + ({session_id:$session,loop_id:"loop-new",revision:2,wave_id:"wave-2",node_id:$node}|tojson)')
    jq -cn --arg session "$1" --arg cwd "$CWD" --arg st "$3" --argjson prompt "$prompt" \
        '{tool_name:"Agent",session_id:$session,cwd:$cwd,tool_input:{subagent_type:$st,prompt:$prompt}}'
}

# NEGATIVE — a downstream node dispatched as a NON-loop-worker type, 3-unit
# roster, no evals at all -> DENIED. This is the whole gap: before this change
# coderails:docs-auditor exited the gate before the evals read was ever
# reached.
reset
graph_state S1 S9-docs
out=$(run "$(typed_graph_payload S1 S9-docs coderails:docs-auditor)")
is_denied "$out"
check "graph-owned docs-auditor at downstream node, no evals -> BLOCK" 0 $?

# POSITIVE — the identical dispatch with a valid frozen suite -> ALLOWED. A
# change that denied everything unconditionally would pass the negative case
# above and fail here.
reset
graph_state S1 S9-docs
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
out=$(run "$(typed_graph_payload S1 S9-docs coderails:docs-auditor)")
check "graph-owned docs-auditor at downstream node, frozen suite -> allow" "" "$out"

# BOOTSTRAP — the eval-authoring nodes necessarily run BEFORE evals exist.
# Gating them would make the node that writes evals.json undispatchable.
reset
graph_state S1 S2.7c
out=$(run "$(typed_graph_payload S1 S2.7c coderails:task-evals)")
check "eval-authoring node S2.7c, no evals.json -> allow (bootstrap)" "" "$out"

reset
graph_state S1 S2.7e
out=$(run "$(typed_graph_payload S1 S2.7e coderails:proof-author)")
check "eval-authoring node S2.7e, no evals.json -> allow (bootstrap)" "" "$out"

# Pre-freeze scouts produce the material evals are written FROM, so they are
# exempt too. S2-audit is a real ad-hoc runtime id absent from the role table;
# it must classify by its S2 prefix, not by role resolution.
reset
graph_state S1 S2
out=$(run "$(typed_graph_payload S1 S2 coderails:preflight-scout)")
check "pre-freeze node S2, no evals.json -> allow (bootstrap)" "" "$out"

reset
graph_state S1 S2-audit
out=$(run "$(typed_graph_payload S1 S2-audit coderails:preflight-scout)")
check "unmapped pre-freeze node S2-audit, no evals.json -> allow (bootstrap)" "" "$out"

# The exemption must NOT become a loop-worker bypass: a coderails:loop-worker
# dispatched under an eval-authoring node id is still gated. Keying the
# exemption purely on node id, evaluated ahead of is_worker, would open a hole
# in the exact path this gate was built for.
reset
graph_state S1 S2.7c
out=$(run "$(typed_graph_payload S1 S2.7c coderails:loop-worker)")
is_denied "$out"
check "loop-worker under an eval-authoring node id -> BLOCK (no bypass)" 0 $?

# An unrecognised node id fails CLOSED, not open.
reset
graph_state S1 U3-b
out=$(run "$(typed_graph_payload S1 U3-b coderails:docs-auditor)")
is_denied "$out"
check "unmapped downstream node U3-b, no evals -> BLOCK (fail closed)" 0 $?

# REGRESSION — a non-graph loop (no .graph key) keeps its old behaviour: a
# non-worker Agent call is not gate-eligible, so it stays outside this gate.
# Widening to arbitrary Agent calls would risk locking out the session.
reset
write_file S1 "$WU3_PENDING"
out=$(run "$(payload S1 coderails:preflight-scout)")
check "non-graph loop, non-worker Agent call -> allow (unchanged)" "" "$out"

# REGRESSION — no progress.json at all: a non-worker Agent call must still be
# allowed. Denying here would block every Agent dispatch in any session with
# no loop state, which is a session lockout. A graph-owned dispatch cannot
# reach this path: gate-eligibility requires .graph to be an object in an
# existing state file, so the envelope below is validated only when state
# exists. Nothing else in this suite pins that line.
reset
out=$(run "$(payload S1 coderails:preflight-scout)")
check "no progress.json, non-worker Agent call -> allow (no lockout)" "" "$out"
out=$(run "$(typed_graph_payload S1 S9-docs coderails:docs-auditor)")
check "no progress.json, graph-enveloped non-worker -> allow (no lockout)" "" "$out"

# REGRESSION — #433's FROZEN acceptance still holds at dispatch for a
# graph-owned non-worker node.
reset
graph_state S1 S9-wiki
frozen_evals S1 "$P0_PENDING" 2 "$JUST"
out=$(run "$(typed_graph_payload S1 S9-wiki coderails:wiki-writer)")
check "FROZEN still accepted at dispatch for a graph-owned wiki-writer" "" "$out"

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
