#!/usr/bin/env bash
# Provenance binding for Claude graph evidence, continued from
# graph_evidence.test.sh (split for the repo's file-size ceiling — same
# fixture setup, same helpers, no behaviour change). Covers: mailbox/teammate
# dispatch (SendMessage / named `Agent(name: ...)`) cannot bind a "done"
# node, the async/task-notification dispatch style stays untouched, and a
# sidechain replay cannot override a genuine mailbox refusal.
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
mkdir -p "$PROJECTS"

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

# ---------------------------------------------------------------------------
# Mailbox/teammate dispatch (SendMessage / named `Agent(name: ...)`): a spawn
# whose tool_result carries .toolUseResult.status=="teammate_spawned" cannot
# bind a "done" node — its completion arrives as a <teammate-message>, which
# carries no harness-stamped discriminator to correlate it back to this spawn.
# ---------------------------------------------------------------------------
append_tool_result() { # projects_dir session_id tool_use_id status
	local projects="$1" session="$2" tool_use_id="$3" status="$4" path
	path=$(claude_fixture::transcript "$projects" "$session")
	jq -cn --arg session "$session" --arg tid "$tool_use_id" --arg status "$status" '
      {type:"user",sessionId:$session,isSidechain:false,
       message:{content:[{tool_use_id:$tid,type:"tool_result",content:[{type:"text",text:"x"}]}]},
       toolUseResult:{status:$status}}' >>"$path"
}

MAILBOX_SESSION="session-fixture-mailbox"
claude_fixture::init "$PROJECTS" "$MAILBOX_SESSION"
MAILBOX_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$MAILBOX_SESSION")
MAILBOX_SPAWN=$(claude_fixture::append_spawn "$PROJECTS" "$MAILBOX_SESSION" N1 wave-1 toolu_MAILBOXSPAWN1)
append_tool_result "$PROJECTS" "$MAILBOX_SESSION" "$MAILBOX_SPAWN" teammate_spawned
state="$TMP/mailbox_refused.json"
jq -n --arg session "$MAILBOX_SESSION" --argjson c "$MAILBOX_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "a mailbox-dispatched done node is refused, not silently bound" \
	"mailbox/teammate" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')"

# --- the async/task-notification dispatch style is untouched: a genuine
# async_launched spawn with a real completed notification still binds ---
ASYNC_SESSION="session-fixture-async-status"
claude_fixture::init "$PROJECTS" "$ASYNC_SESSION"
ASYNC_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$ASYNC_SESSION")
ASYNC_SPAWN=$(claude_fixture::append_spawn "$PROJECTS" "$ASYNC_SESSION" N1 wave-1 toolu_ASYNCSTATUS01)
append_tool_result "$PROJECTS" "$ASYNC_SESSION" "$ASYNC_SPAWN" async_launched
append_notification "$PROJECTS" "$ASYNC_SESSION" "$ASYNC_SPAWN" completed
state="$TMP/async_status_binds.json"
jq -n --arg session "$ASYNC_SESSION" --argjson c "$ASYNC_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
if graph_dispatch_record "$state" "$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1; then
	pass "an async_launched-status done node still binds (untouched path)"
else
	fail "an async_launched-status done node still binds (untouched path)" \
		"record refused a genuine async_launched spawn with a completed notification"
fi

# --- a sidechain replay of the SAME tool_use_id with a later async_launched
# status must not override the genuine main-thread teammate_spawned status:
# from_entries takes the last key, so an unfiltered walk would let this
# silently un-refuse the mailbox guard ---
SIDECHAIN_SESSION="session-fixture-mailbox-sidechain"
claude_fixture::init "$PROJECTS" "$SIDECHAIN_SESSION"
SIDECHAIN_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$SIDECHAIN_SESSION")
SIDECHAIN_SPAWN=$(claude_fixture::append_spawn "$PROJECTS" "$SIDECHAIN_SESSION" N1 wave-1 toolu_SIDECHAINMB1)
append_tool_result "$PROJECTS" "$SIDECHAIN_SESSION" "$SIDECHAIN_SPAWN" teammate_spawned
SIDECHAIN_PATH=$(claude_fixture::transcript "$PROJECTS" "$SIDECHAIN_SESSION")
jq -cn --arg tid "$SIDECHAIN_SPAWN" --arg session "$SIDECHAIN_SESSION" '
  {type:"user",sessionId:$session,isSidechain:true,
   message:{content:[{tool_use_id:$tid,type:"tool_result",content:[{type:"text",text:"x"}]}]},
   toolUseResult:{status:"async_launched"}}' >>"$SIDECHAIN_PATH"
state="$TMP/mailbox_sidechain_refused.json"
jq -n --arg session "$SIDECHAIN_SESSION" --argjson c "$SIDECHAIN_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "a sidechain-replayed async status cannot override a genuine mailbox refusal" \
	"mailbox/teammate" "$state" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')"

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS\n'
else
	printf 'FAIL (%d)\n' "$FAILS"
	exit 1
fi
