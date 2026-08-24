#!/usr/bin/env bash
# Provenance binding for Claude graph evidence, continued from
# graph_evidence.test.sh (split for the repo's file-size ceiling — same
# fixture setup, same helpers, no behaviour change). Covers: the
# terminal-result/notification requirement for "done" nodes, identity
# binding (caller-supplied .agent_id, shared task-id reuse), session
# mismatch, and an unreadable transcript with a claim to check against it.
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

# ---------------------------------------------------------------------------
# Terminal-result requirement: a real, cursor-valid spawn is not enough — a
# 'done' node also needs a matching parent-transcript <task-notification>
# reporting status=completed with a non-empty result before it can bind.
# ---------------------------------------------------------------------------

# --- a matching notification reporting status=failed refuses with a NAMED
# notification-status reason ---
NOTIF_SESSION="session-fixture-notif-failed"
claude_fixture::init "$PROJECTS" "$NOTIF_SESSION"
NOTIF_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$NOTIF_SESSION")
NOTIF_SPAWN=$(claude_fixture::append_spawn "$PROJECTS" "$NOTIF_SESSION" N1 wave-1 toolu_NOTIFFAILED01)
append_notification "$PROJECTS" "$NOTIF_SESSION" "$NOTIF_SPAWN" failed
state="$TMP/notif_failed.json"
jq -n --arg session "$NOTIF_SESSION" --argjson c "$NOTIF_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "a done node whose only notification reports failed is refused" \
	"notification status" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')"

# --- a matching notification reporting status=killed refuses the same way ---
NOTIF_KILLED_SESSION="session-fixture-notif-killed"
claude_fixture::init "$PROJECTS" "$NOTIF_KILLED_SESSION"
NOTIF_KILLED_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$NOTIF_KILLED_SESSION")
NOTIF_SPAWN2=$(claude_fixture::append_spawn "$PROJECTS" "$NOTIF_KILLED_SESSION" N1 wave-1 toolu_NOTIFKILLED01)
append_notification "$PROJECTS" "$NOTIF_KILLED_SESSION" "$NOTIF_SPAWN2" killed
state="$TMP/notif_killed.json"
jq -n --arg session "$NOTIF_KILLED_SESSION" --argjson c "$NOTIF_KILLED_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "a done node whose only notification reports killed is refused" \
	"notification status" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')"

# --- a real spawn with NO matching notification at all is refused with a
# NAMED missing-notification reason ---
MISSING_SESSION="session-fixture-notif-missing"
claude_fixture::init "$PROJECTS" "$MISSING_SESSION"
MISSING_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$MISSING_SESSION")
claude_fixture::append_spawn "$PROJECTS" "$MISSING_SESSION" N1 wave-1 toolu_NOTIFMISSING01 >/dev/null
state="$TMP/notif_missing.json"
jq -n --arg session "$MISSING_SESSION" --argjson c "$MISSING_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "a done node with no matching notification at all is refused" \
	"no completed notification" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')"

# --- a completed notification with a non-empty result binds successfully ---
GOOD_SESSION="session-fixture-notif-good"
claude_fixture::init "$PROJECTS" "$GOOD_SESSION"
GOOD_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$GOOD_SESSION")
GOOD_SPAWN=$(claude_fixture::append_spawn "$PROJECTS" "$GOOD_SESSION" N1 wave-1 toolu_NOTIFGOOD01)
append_notification "$PROJECTS" "$GOOD_SESSION" "$GOOD_SPAWN" completed
state="$TMP/notif_good.json"
jq -n --arg session "$GOOD_SESSION" --argjson c "$GOOD_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
if graph_dispatch_record "$state" "$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1; then
	expect_eq "a completed notification with a result binds successfully" 'true' \
		"$(jq -r --arg id "$GOOD_SPAWN" '[.graph.nodes.N1.evidence[]
            | select(type=="object" and .kind=="claude_agent")]
           | length == 1 and .[0].tool_use_id == $id
             and (.[0].agent_id | type == "string" and length > 0)' "$state")"
else
	fail "a completed notification with a result binds successfully" "record refused a genuine completed spawn"
fi

# ---------------------------------------------------------------------------
# Identity binding: a caller-supplied .agent_id claim is forged provenance,
# and one underlying agent identity (shared task-id) cannot bind to two nodes.
# ---------------------------------------------------------------------------

# --- a caller-supplied .agent_id claim (no spawn_ref/tool_use_id) is a forged
# provenance claim and is refused with a NAMED agent_id reason ---
state="$TMP/agentid_forged.json"
write_state "$state" "$CURSOR"
smuggled_agent_id=$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:[{note:"x",d:{agent_id:"agt_FORGEDCLAIM"}}]},
    N2:{outcome:"done",evidence:[]}}}')
if out=$(graph_dispatch_record "$state" "$smuggled_agent_id" 2>&1); then
	fail "a caller-supplied .agent_id claim is refused" "accepted a nested .agent_id provenance claim"
elif ! printf '%s' "$out" | grep -q -- 'agent_id'; then
	fail "a caller-supplied .agent_id claim is refused" "refused, but not for an agent_id reason; got: $out"
else
	pass "a caller-supplied .agent_id claim is refused"
fi

# --- two distinct genuine spawns for two different nodes, sharing ONE
# underlying task-id, must not both bind: one agent identity, two nodes ---
REUSE_SESSION="session-fixture-agentid-reuse"
claude_fixture::init "$PROJECTS" "$REUSE_SESSION"
REUSE_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$REUSE_SESSION")
REUSE_SPAWN1=$(claude_fixture::append_spawn "$PROJECTS" "$REUSE_SESSION" N1 wave-1 toolu_REUSEIDENT01)
REUSE_SPAWN2=$(claude_fixture::append_spawn "$PROJECTS" "$REUSE_SESSION" N2 wave-1 toolu_REUSEIDENT02)
SHARED_TASK="shared-underlying-agent-task-id"
append_notification "$PROJECTS" "$REUSE_SESSION" "$REUSE_SPAWN1" completed "$SHARED_TASK"
append_notification "$PROJECTS" "$REUSE_SESSION" "$REUSE_SPAWN2" completed "$SHARED_TASK"
state="$TMP/agentid_reuse.json"
jq -n --arg session "$REUSE_SESSION" --argjson c "$REUSE_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
if out=$(graph_dispatch_record "$state" "$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:[]},N2:{outcome:"done",evidence:[]}}}')" 2>&1); then
	fail "one agent identity (shared task-id) cannot bind two nodes" \
		"accepted binding one underlying agent identity to two different nodes"
elif ! printf '%s' "$out" | grep -q -- 'agent_id'; then
	fail "one agent identity (shared task-id) cannot bind two nodes" \
		"refused, but not for an agent_id reuse reason; got: $out"
else
	pass "one agent identity (shared task-id) cannot bind two nodes"
fi

# ---------------------------------------------------------------------------
# Session mismatch: an Agent-spawn envelope whose embedded session_id does
# not match progress.json's top-level session_id is refused with a NAMED
# session-naming reason, not the silent generic "nothing to bind" path.
# ---------------------------------------------------------------------------
WRONGSESSION="session-fixture-wrongsession"
WRONGSESSION_PATH=$(claude_fixture::transcript "$PROJECTS" "$WRONGSESSION")
mkdir -p "$(dirname "$WRONGSESSION_PATH")"
: >"$WRONGSESSION_PATH"
WS_ENV=$(jq -cn '{session_id:"session-FOREIGN",loop_id:"loop-fixture",revision:1,wave_id:"wave-1",node_id:"N1"}')
jq -cn --arg session "$WRONGSESSION" --arg envelope "$WS_ENV" '{
    type:"assistant",uuid:"uuid-wrongsession",parentUuid:"parent-wrongsession",
    sessionId:$session,isSidechain:false,
    message:{content:[{type:"tool_use",id:"toolu_WRONGSESSION01",name:"Agent",
      input:{description:"dispatch N1",subagent_type:"coderails:loop-worker",
             prompt:("CODERAILS_GRAPH_DISPATCH=" + $envelope + "\nbody")}}]}
  }' >>"$WRONGSESSION_PATH"
WS_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$WRONGSESSION")
state="$TMP/wrongsession.json"
jq -n --arg session "$WRONGSESSION" --argjson c "$WS_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
if out=$(graph_dispatch_record "$state" "$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" 2>&1); then
	fail "a session-mismatched envelope is refused" "accepted a done node bound via a session-mismatched envelope"
elif ! printf '%s' "$out" | grep -qi -- 'session'; then
	fail "a session-mismatched envelope is refused" "refused, but with no session-naming reason; got: $out"
else
	pass "a session-mismatched envelope is refused"
fi

# ---------------------------------------------------------------------------
# Transcript unreadable at bind-time, with a claim to check against it, is
# refused with a NAMED transcript-naming reason.
# ---------------------------------------------------------------------------
state="$TMP/unreadable_claim.json"
jq -n --arg session "session-fixture-notranscript-claim" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:0},
            hard_stop:null}}' >"$state"
if out=$(CLAUDE_PROJECTS_DIR="$EMPTY_PROJECTS" graph_dispatch_record "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[{spawn_ref:"toolu_CLAIMEDBUTNONE"}]}}}')" 2>&1); then
	fail "a cited claim with no resolvable transcript names the transcript reason" \
		"accepted a claim with no resolvable transcript"
elif ! printf '%s' "$out" | grep -qi -- 'transcript'; then
	fail "a cited claim with no resolvable transcript names the transcript reason" \
		"refused, but not with a transcript-naming reason; got: $out"
else
	pass "a cited claim with no resolvable transcript names the transcript reason"
fi

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS\n'
else
	printf 'FAIL (%d)\n' "$FAILS"
	exit 1
fi
