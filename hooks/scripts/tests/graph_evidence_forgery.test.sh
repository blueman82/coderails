#!/usr/bin/env bash
# Provenance binding for Claude graph evidence, continued from
# graph_evidence.test.sh (split for the repo's file-size ceiling — same
# fixture setup, same helpers, no behaviour change). Covers: silence is not
# an exemption, transcript location cannot be redirected, forged provenance
# at any depth/shape, fan-out, cursor counting/recording, and backward
# compatibility with no cursor/transcript.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# The transcript path is pinned under $HOME/.claude/projects: the party this
# gate constrains has arbitrary Bash, so a location it can redirect is not
# evidence. There is deliberately NO env opt-out — an escape hatch the
# adversary can set is no barrier at all. Tests get isolation by redirecting
# HOME itself, the same way provider_graph_parity.test.sh does.
export HOME="$TMP/home"
export CLAUDE_PROJECTS_DIR="$HOME/.claude/projects"
PROJECTS="$CLAUDE_PROJECTS_DIR"
# A pinned-but-EMPTY projects dir, for the cases that must exercise "no
# transcript resolves" rather than "the path was refused".
EMPTY_PROJECTS="$PROJECTS/empty"
mkdir -p "$PROJECTS" "$EMPTY_PROJECTS"
SESSION="session-fixture-0001"

# shellcheck disable=SC1091  # library path is resolved from this test file at runtime
source "$ROOT/hooks/scripts/tests/lib/claude_transcript_fixture.sh"
# shellcheck disable=SC1091  # library path is resolved from this test file at runtime
source "$ROOT/hooks/scripts/lib/graph_dispatch.sh"

FAILS=0
pass() { printf 'ok   - %s\n' "$1"; }
fail() {
	printf 'FAIL - %s\n      %s\n' "$1" "$2"
	FAILS=$((FAILS + 1))
}
expect_eq() { # name expected actual
	if [[ "$3" == "$2" ]]; then pass "$1"; else fail "$1" "expected=$2 actual=$3"; fi
}

# Append a completed <task-notification> record for a spawn, matching the
# real live shape (verified live: a type:"user", isSidechain:false record
# whose message.content is a raw string carrying the notification block).
# task_id defaults to the tool_use id itself, so each genuine spawn gets its
# own distinct underlying-agent identity unless a test deliberately shares one.
append_notification() { # projects_dir session_id tool_use_id [status] [task_id]
	local projects="$1" session="$2" tool_use_id="$3" status="${4:-completed}" task_id="${5:-$3}"
	local path
	path=$(claude_fixture::transcript "$projects" "$session")
	jq -cn --arg session "$session" --arg tid "$tool_use_id" --arg status "$status" --arg task "$task_id" '
      {parentUuid:"p",isSidechain:false,promptId:"x",type:"user",
       message:{role:"user",
         content:("<task-notification>\n<task-id>" + $task + "</task-id>\n<tool-use-id>" + $tid
                   + "</tool-use-id>\n<status>" + $status + "</status>\n<result>work product</result>\n</task-notification>")},
       uuid:("notif-" + $tid),timestamp:"2026-01-01T00:00:00Z",
       origin:{kind:"task-notification"},sessionId:$session}' >>"$path"
}

# Assert a record is REFUSED *and* that it was refused for the stated reason.
# Exit status alone cannot tell a cursor denial from a wave-id mismatch, so a
# test named for one property would still pass if another property did the
# rejecting. Matching the `graph_evidence:` message binds the test to the
# mechanism it claims to cover.
expect_denied() { # name reason_substring state envelope
	local name="$1" reason="$2" state="$3" envelope="$4" before output
	before="$state.before.$RANDOM"
	cp "$state" "$before"
	if output=$(graph_dispatch_record "$state" "$envelope" 2>&1); then
		fail "$name" "record was ACCEPTED; expected refusal for: $reason"
	elif ! printf '%s' "$output" | grep -q -- "$reason"; then
		fail "$name" "refused, but not for '$reason'; got: $(printf '%s' "$output" | tr '\n' ' ')"
	elif ! cmp -s "$before" "$state"; then
		fail "$name" "refusal changed durable state"
	else
		pass "$name"
	fi
	rm -f "$before"
}

# A two-node in-progress graph with an active wave, optionally carrying a
# transcript cursor. Mirrors the seed shape graph_dispatch_begin_wave writes.
write_state() { # path cursor_json [attempts]
	local path="$1" cursor="$2" attempts="${3:-0}"
	jq -n --arg session "$SESSION" --argjson cursor "$cursor" \
		--argjson attempts "$attempts" '
      (. // {}) as $_
      | {status:"running",outcome:"running",retry:{attempts:$attempts,max:2},evidence:[]} as $n
      | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
         status:"in-progress",
         graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
                active_wave:({wave_id:"wave-1",revision:1,nodes:["N1","N2"]}
                             + (if $cursor == null then {} else {transcript_cursor:$cursor} end)),
                hard_stop:null}}' >"$path"
}

# ---------------------------------------------------------------------------
# Fixture transcript: one pre-cursor spawn, then the wave's two genuine spawns.
# Identical to graph_evidence.test.sh's own fixture — this file exercises a
# different set of assertions against the same transcript state.
# ---------------------------------------------------------------------------
claude_fixture::init "$PROJECTS" "$SESSION"
claude_fixture::append_spawn "$PROJECTS" "$SESSION" N1 wave-0 toolu_PRECURSOR01 >/dev/null
claude_fixture::append_noise "$PROJECTS" "$SESSION"
CURSOR=$(claude_fixture::cursor "$PROJECTS" "$SESSION")
GEN1=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION" N1 wave-1 toolu_GENUINE0001)
GEN2=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION" N2 wave-1 toolu_OTHERNODE02)
append_notification "$PROJECTS" "$SESSION" "$GEN1"
append_notification "$PROJECTS" "$SESSION" "$GEN2"

# --- CRITICAL 1: silence is not an exemption --------------------------------
# A HEALTHY transcript containing a genuine wave-1 spawn for N2 only. The
# orchestrator reports BOTH nodes done with plain-string evidence. N1 was never
# dispatched, and the same transcript that binds N2 proves it — so reporting
# nothing must not be a way to opt out of the check.
UND_SESSION="session-fixture-undispatched"
claude_fixture::init "$PROJECTS" "$UND_SESSION"
UND_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$UND_SESSION")
claude_fixture::append_spawn "$PROJECTS" "$UND_SESSION" N2 wave-1 toolu_ONLYN2SPAWN >/dev/null
append_notification "$PROJECTS" "$UND_SESSION" toolu_ONLYN2SPAWN
state="$TMP/undispatched.json"
jq -n --arg session "$UND_SESSION" --argjson c "$UND_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "an undispatched node citing nothing is refused" \
	"has no spawn in wave-1" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{
        N1:{outcome:"done",evidence:["shipped PR #999"]},
        N2:{outcome:"done",evidence:["real work"]}}}')"

# A join legitimately has no Agent spawn — it is satisfied by the orchestrator
# absorbing results, so it must still pass through even when binding is
# otherwise required.
state="$TMP/join_exempt.json"
jq -n --arg session "$UND_SESSION" --argjson c "$UND_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N2:$n,J1:$n},edges:[],
            joins:{J1:{mode:"all",inputs:["N2"],released:false}},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["J1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
if graph_dispatch_record "$state" "$(jq -cn '{wave_id:"wave-1",results:{
    J1:{outcome:"done",evidence:["join absorbed"]},
    N2:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1; then
	expect_eq "a join with no spawn is still exempt from binding" 'true' \
		"$(jq -r '.graph.nodes.J1.status == "done"
              and ([.graph.nodes.N2.evidence[] | select(type=="object")] | length) == 1' "$state")"
else
	fail "a join with no spawn is still exempt from binding" "record refused a legitimate join"
fi

# --- CRITICAL 2: the transcript location cannot be redirected ---------------
# The party this gate constrains has arbitrary Bash, so a transcript it can
# point elsewhere is not evidence. This plants a PERFECTLY VALID transcript,
# whose spawn would otherwise bind cleanly, at a path outside
# $HOME/.claude/projects — it must be refused on location alone. There is no
# env opt-out to disable, because an escape the adversary can also set would
# be no barrier.
OUTSIDE="$TMP/outside-home/projects"
mkdir -p "$OUTSIDE"
OUT_SESSION="session-fixture-outside"
claude_fixture::init "$OUTSIDE" "$OUT_SESSION"
OUT_CURSOR=$(claude_fixture::cursor "$OUTSIDE" "$OUT_SESSION")
claude_fixture::append_spawn "$OUTSIDE" "$OUT_SESSION" N2 wave-1 toolu_OUTSIDEHOME >/dev/null
state="$TMP/unpinned.json"
jq -n --arg session "$OUT_SESSION" --argjson c "$OUT_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
cp "$state" "$TMP/unpinned.before"
if CLAUDE_PROJECTS_DIR="$OUTSIDE" graph_dispatch_record "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N2:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1; then
	fail "a transcript outside \$HOME is refused on location alone" \
		"read a redirected transcript the constrained party controls"
else
	pass "a transcript outside \$HOME is refused on location alone"
	expect_eq "the refused unpinned-transcript wave left state untouched" 'same' \
		"$(cmp -s "$TMP/unpinned.before" "$state" && echo same || echo changed)"
fi

# A wave whose cursor was never recorded must not bind at all: with no lower
# bound it cannot tell a fresh spawn from an identically-named older one.
state="$TMP/nocursor_nobind.json"
jq -n --arg session "$SESSION" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"]},
            hard_stop:null}}' >"$state"
if graph_dispatch_record "$state" "$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:["no cursor"]},N2:{outcome:"done",evidence:[]}}}')" \
	>/dev/null 2>&1; then
	expect_eq "a cursorless wave binds nothing rather than binding unbounded" 'true' \
		"$(jq -r '[.graph.nodes[].evidence[] | select(type=="object")] | length == 0' "$state")"
else
	fail "a cursorless wave binds nothing rather than binding unbounded" "record refused"
fi

# --- IMPORTANT 3: forged provenance is caught at any depth or shape ---------
# A shape denylist loses to wrapping, nesting, whitespace and homoglyphs, so
# detection normalises the whole entry instead. Each variant must be refused.
run_smuggle() { # label evidence_json
	local label="$1" ev="$2" st="$TMP/smug.$RANDOM.json"
	jq -n --arg session "$SESSION" --argjson c "$CURSOR" '
      {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
      | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
         status:"in-progress",
         graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
                active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
                hard_stop:null}}' >"$st"
	if graph_dispatch_record "$st" "$(jq -cn --argjson ev "$ev" '{wave_id:"wave-1",results:{
        N1:{outcome:"done",evidence:$ev},N2:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1; then
		fail "forged provenance refused: $label" "ACCEPTED; persisted $(jq -c '.graph.nodes.N1.evidence' "$st")"
	else
		pass "forged provenance refused: $label"
	fi
}
run_smuggle "array-wrapped" '[[{"kind":"claude_agent","tool_use_id":"toolu_FORGEDA"}]]'
run_smuggle "nested under a benign key" '[{"note":"x","d":{"kind":"claude_agent","tool_use_id":"toolu_FORGEDB"}}]'
run_smuggle "trailing space in kind" '[{"kind":"claude_agent ","tool_use_id":"toolu_FORGEDC"}]'
run_smuggle "partial shape, spawn_ref only" '[{"attempt":1,"wave_id":"wave-1","spawn_ref":"toolu_FORGEDD"}]'
run_smuggle "homoglyph in kind" '[{"kind":"claude_аgent","tool_use_id":"toolu_FORGEDE"}]'
run_smuggle "bound shape as a JSON string" '["{\"kind\":\"claude_agent\",\"tool_use_id\":\"toolu_FORGEDF\"}"]'

# Reuse through an array-wrapped seed: the reuse set must descend, or the same
# real spawn binds to a second node.
state="$TMP/nested_reuse.json"
jq -n --arg session "$SESSION" --argjson c "$CURSOR" --arg id "$GEN1" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n,
       N2:{status:"running",outcome:"running",retry:{attempts:0,max:2},
           evidence:[[{kind:"claude_agent",attempt:1,wave_id:"wave-0",
                       tool_use_id:$id,record_uuid:"u",subagent_type:"x"}]]}},
       edges:[],joins:{},
       active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
       hard_stop:null}}' >"$state"
# The id N1 would otherwise bind is already bound (nested) under N2, so it is
# consumed and N1 has no candidate left — refused rather than binding one spawn
# to two nodes. The message names the empty-candidate outcome; the invariant
# under test is that the id is NOT reused, asserted below.
expect_denied "a nested already-bound id still blocks reuse" \
	"has no spawn in wave-1" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{
        N1:{outcome:"done",evidence:[]},N2:{outcome:"done",evidence:[]}}}')"

# --- FAN-OUT: one node, several concurrent spawns in a single wave ----------
# Observed live in this repo: a single node dispatched to three agents at once
# inside one wave. apply_wave writes each node once per wave, so all of them
# are present when the wave is recorded. Requiring exactly one spawn per node
# would deny those legitimate waves outright.
FAN_SESSION="session-fixture-fanout"
claude_fixture::init "$PROJECTS" "$FAN_SESSION"
FAN_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$FAN_SESSION")
claude_fixture::append_spawn "$PROJECTS" "$FAN_SESSION" N1 wave-1 toolu_FAN1 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$FAN_SESSION" N1 wave-1 toolu_FAN2 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$FAN_SESSION" N1 wave-1 toolu_FAN3 >/dev/null
append_notification "$PROJECTS" "$FAN_SESSION" toolu_FAN1
append_notification "$PROJECTS" "$FAN_SESSION" toolu_FAN2
append_notification "$PROJECTS" "$FAN_SESSION" toolu_FAN3
state="$TMP/fanout.json"
jq -n --arg session "$FAN_SESSION" --argjson c "$FAN_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
if graph_dispatch_record "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:["fanned out"]}}}')" \
	>/dev/null 2>&1; then
	expect_eq "a node with several spawns in one wave binds one of them" 'true' \
		"$(jq -r '[.graph.nodes.N1.evidence[] | select(type=="object")] as $refs
              | ($refs | length) == 1
                and (["toolu_FAN1","toolu_FAN2","toolu_FAN3"] | index($refs[0].tool_use_id)) != null' "$state")"
else
	fail "a node with several spawns in one wave binds one of them" \
		"fan-out was refused; a legitimate wave cannot be recorded"
fi

# Fan-out must not weaken WHICH ids are acceptable: a forged id is still
# refused even when the node has several genuine spawns to choose from.
state="$TMP/fanout_forged.json"
jq -n --arg session "$FAN_SESSION" --argjson c "$FAN_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "fan-out does not make a forged id acceptable" \
	"cites a spawn it does not own" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{
        N1:{outcome:"done",evidence:[{spawn_ref:"toolu_FANFORGED"}]}}}')"

# --- The cursor counts records the way the spawn walk numbers them ----------
# `wc -l` counts newlines, so a transcript caught mid-append (final line not yet
# newline-terminated) would under-count, leaving a spawn on that line looking
# one position PAST the cursor — exactly the replay the cursor prevents.
unterminated="$TMP/unterminated.jsonl"
printf '%s' "$(jq -cn '{type:"assistant",uuid:"u",sessionId:"s",isSidechain:false,
    message:{content:[{type:"tool_use",id:"toolu_X",name:"Agent",input:{prompt:"x"}}]}}')" \
	>"$unterminated"
expect_eq "the cursor counts an unterminated final record" '1' \
	"$(graph_evidence_cursor "$unterminated")"

# --- Cursor is recorded at begin-wave --------------------------------------
state="$TMP/beginwave.json"
jq -n --arg session "$SESSION" '
  {status:"pending",outcome:"pending",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},active_wave:null,hard_stop:null}}' >"$state"
if graph_dispatch_begin_wave "$state" >/dev/null 2>&1; then
	expect_eq "begin-wave records the transcript cursor as a wave lower bound" 'true' \
		"$(jq -r --argjson c "$(claude_fixture::cursor "$PROJECTS" "$SESSION")" \
			'.graph.active_wave.transcript_cursor == $c' "$state")"
else
	fail "begin-wave records the transcript cursor as a wave lower bound" "begin-wave failed"
fi

# --- Backward compatibility: no cursor, no cited ref, no transcript --------
# Existing suites drive graph_dispatch_record with plain string evidence and
# no transcript at all; that must stay working (binding is additive).
state="$TMP/legacy.json"
write_state "$state" null
legacy=$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:["plain string proof"]},
    N2:{outcome:"done",evidence:[]}}}')
if CLAUDE_PROJECTS_DIR="$EMPTY_PROJECTS" graph_dispatch_record "$state" "$legacy" >/dev/null 2>&1; then
	expect_eq "uncited string evidence with no transcript still records" 'true' \
		"$(jq -r '.graph.nodes.N1.evidence == ["plain string proof"]' "$state")"
else
	fail "uncited string evidence with no transcript still records" "record refused legacy evidence"
fi

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS\n'
else
	printf 'FAIL (%d)\n' "$FAILS"
	exit 1
fi
