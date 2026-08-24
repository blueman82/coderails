#!/usr/bin/env bash
# graph_dispatch_complete.test.sh — completion-time revalidation.
#
# graph_dispatch_record binds each "done" node's evidence to a real, verified
# Agent spawn at record-time. graph_dispatch_complete must not trust that
# binding forever: it re-checks EVERY "done" node's already-bound evidence
# again (notification lookup + status + result + agent_id/tool_use_id global
# uniqueness) immediately before allowing the graph to complete, so a
# transcript mutated after binding (or an evidence array hand-edited after
# the fact) cannot slip a graph to completion on stale trust.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP/home"
export CLAUDE_PROJECTS_DIR="$HOME/.claude/projects"
PROJECTS="$CLAUDE_PROJECTS_DIR"
mkdir -p "$PROJECTS"

# shellcheck source=hooks/scripts/tests/lib/claude_transcript_fixture.sh
source "$ROOT/hooks/scripts/tests/lib/claude_transcript_fixture.sh"
# shellcheck source=hooks/scripts/lib/graph_dispatch.sh
source "$ROOT/hooks/scripts/lib/graph_dispatch.sh"
# shellcheck source=scripts/lib/eval-artifact.sh
source "$ROOT/scripts/lib/eval-artifact.sh"

FAILS=0
pass() { printf 'ok   - %s\n' "$1"; }
fail() {
	printf 'FAIL - %s\n      %s\n' "$1" "$2"
	FAILS=$((FAILS + 1))
}

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

# Build a fully valid evals/proof/retro triple for the given session/loop at
# progress.json's current revision, so graph_dispatch_complete's own
# non-provenance gates (evals GO, proof pass, retro complete) are satisfied
# and only the revalidation behaviour under test can fail it.
write_valid_triple() { # session loop revision evals_path proof_path retro_path
	local session="$1" loop="$2" revision="$3" evals="$4" proof="$5" retro="$6"
	jq -n --arg session "$session" --arg loop "$loop" --argjson revision "$revision" '
      {schema_version:1,scope:"loop",task_ref:"t",verification_level:1,
       verification_justification:"fixture",frozen_at:"2026-01-01T00:00:00Z",
       frozen_sha:"deadbeef",session_id:$session,loop_id:$loop,revision:$revision,
       evals:[{id:"E1",priority:"P0",mode:"scripted",surface:"merged-state",
               assert:"x",cmd:"true",negative_control:"false",status:"pass",evidence:"e"}],
       amendments:[],result:null,graded_at:null,head_sha:null}' >"$evals"
	eval_artifact::compute_go "$evals"
	local checksum
	checksum=$(eval_artifact::grading_checksum "$evals" GO)
	jq --arg cs "$checksum" '.result = "GO" | .graded_at = "2026-01-01T00:00:01Z"
      | .grading = {by:"post_evals.sh grade-loop", checksum:$cs, amendments_at_grade: (.amendments|length)}' \
		"$evals" >"$evals.tmp" && mv "$evals.tmp" "$evals"
	jq -n --arg session "$session" --arg loop "$loop" \
		'{session_id:$session,loop_id:$loop,proofs:[{status:"pass",evidence:"proved"}]}' >"$proof"
	jq -n --arg session "$session" --arg loop "$loop" \
		'{schema_version:1,session_id:$session,loop_id:$loop,status:"complete"}' >"$retro"
}

# --- a valid, untampered done node completes successfully ------------------
SESSION_VALID="session-complete-valid"
LOOP="loop-fixture"
claude_fixture::init "$PROJECTS" "$SESSION_VALID"
CURSOR_VALID=$(claude_fixture::cursor "$PROJECTS" "$SESSION_VALID")
SPAWN_VALID=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION_VALID" N1 wave-1 toolu_COMPLETEVALID01)
append_notification "$PROJECTS" "$SESSION_VALID" "$SPAWN_VALID" completed
state_valid="$TMP/state_valid.json"
jq -n --arg session "$SESSION_VALID" --arg loop "$LOOP" --argjson c "$CURSOR_VALID" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_valid"
graph_dispatch_record "$state_valid" "$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_record_valid=$?
jq '.graph.active_wave = null | .revision = 2' "$state_valid" >"$state_valid.tmp" && mv "$state_valid.tmp" "$state_valid"
evals_valid="$TMP/evals_valid.json"; proof_valid="$TMP/proof_valid.json"; retro_valid="$TMP/retro_valid.json"
write_valid_triple "$SESSION_VALID" "$LOOP" 2 "$evals_valid" "$proof_valid" "$retro_valid"
if [ "$rc_record_valid" -eq 0 ] &&
	graph_dispatch_complete "$state_valid" --session "$SESSION_VALID" --evals "$evals_valid" --proof "$proof_valid" --retro "$retro_valid" >/dev/null 2>&1; then
	pass "a valid untampered done node completes successfully"
else
	fail "a valid untampered done node completes successfully" \
		"record_rc=$rc_record_valid; completion did not succeed on a genuinely valid triple"
fi

# --- transcript mutated after bind: revalidation blocks completion ---------
SESSION_TAMPER="session-complete-tamper"
claude_fixture::init "$PROJECTS" "$SESSION_TAMPER"
CURSOR_TAMPER=$(claude_fixture::cursor "$PROJECTS" "$SESSION_TAMPER")
SPAWN_TAMPER=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION_TAMPER" N1 wave-1 toolu_COMPLETETAMPER01)
append_notification "$PROJECTS" "$SESSION_TAMPER" "$SPAWN_TAMPER" completed
state_tamper="$TMP/state_tamper.json"
jq -n --arg session "$SESSION_TAMPER" --arg loop "$LOOP" --argjson c "$CURSOR_TAMPER" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_tamper"
graph_dispatch_record "$state_tamper" "$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
jq '.graph.active_wave = null | .revision = 2' "$state_tamper" >"$state_tamper.tmp" && mv "$state_tamper.tmp" "$state_tamper"
evals_tamper="$TMP/evals_tamper.json"; proof_tamper="$TMP/proof_tamper.json"; retro_tamper="$TMP/retro_tamper.json"
write_valid_triple "$SESSION_TAMPER" "$LOOP" 2 "$evals_tamper" "$proof_tamper" "$retro_tamper"

# The transcript is wiped after binding, so N1's already-bound evidence can no
# longer be verified against the parent's own transcript.
transcript_tamper=$(claude_fixture::transcript "$PROJECTS" "$SESSION_TAMPER")
: >"$transcript_tamper"

if out=$(graph_dispatch_complete "$state_tamper" --session "$SESSION_TAMPER" --evals "$evals_tamper" --proof "$proof_tamper" --retro "$retro_tamper" 2>&1); then
	fail "a bound node whose evidence is no longer valid blocks completion" \
		"completion succeeded despite a transcript mutated after binding"
elif ! printf '%s' "$out" | grep -qi -- 'revalidat'; then
	fail "a bound node whose evidence is no longer valid blocks completion" \
		"refused, but not for a revalidation reason; got: $out"
else
	pass "a bound node whose evidence is no longer valid blocks completion"
fi

# --- transcript unparseable at revalidate-time: fails closed with a NAMED
# transcript reason ---
SESSION_UNREADABLE="session-complete-unreadable"
claude_fixture::init "$PROJECTS" "$SESSION_UNREADABLE"
CURSOR_UNREADABLE=$(claude_fixture::cursor "$PROJECTS" "$SESSION_UNREADABLE")
SPAWN_UNREADABLE=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION_UNREADABLE" N1 wave-1 toolu_COMPLETEUNREADABLE01)
append_notification "$PROJECTS" "$SESSION_UNREADABLE" "$SPAWN_UNREADABLE" completed
state_unreadable="$TMP/state_unreadable.json"
jq -n --arg session "$SESSION_UNREADABLE" --arg loop "$LOOP" --argjson c "$CURSOR_UNREADABLE" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_unreadable"
graph_dispatch_record "$state_unreadable" "$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
jq '.graph.active_wave = null | .revision = 2' "$state_unreadable" >"$state_unreadable.tmp" && mv "$state_unreadable.tmp" "$state_unreadable"
evals_unreadable="$TMP/evals_unreadable.json"; proof_unreadable="$TMP/proof_unreadable.json"; retro_unreadable="$TMP/retro_unreadable.json"
write_valid_triple "$SESSION_UNREADABLE" "$LOOP" 2 "$evals_unreadable" "$proof_unreadable" "$retro_unreadable"

transcript_unreadable=$(claude_fixture::transcript "$PROJECTS" "$SESSION_UNREADABLE")
printf 'not json at all\n{"type":"assistant"\n' >"$transcript_unreadable"

if out=$(graph_dispatch_complete "$state_unreadable" --session "$SESSION_UNREADABLE" --evals "$evals_unreadable" --proof "$proof_unreadable" --retro "$retro_unreadable" 2>&1); then
	fail "an unparseable transcript at revalidate-time fails closed" \
		"completion succeeded with an unparseable transcript (fail-open)"
elif ! printf '%s' "$out" | grep -qi -- 'transcript'; then
	fail "an unparseable transcript at revalidate-time fails closed" \
		"refused, but not with a transcript-naming reason; got: $out"
else
	pass "an unparseable transcript at revalidate-time fails closed"
fi

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS\n'
	exit 0
else
	printf 'FAIL (%d)\n' "$FAILS"
	exit 1
fi
