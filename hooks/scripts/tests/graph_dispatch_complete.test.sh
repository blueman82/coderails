#!/usr/bin/env bash
# shellcheck disable=SC2016 # jq programs use single quotes so shell variables stay jq variables.
# shellcheck disable=SC1091 # sourced siblings are resolved at runtime; the gate runs shellcheck without -x.
# graph_dispatch_complete.test.sh — completion-time revalidation.
#
# graph_dispatch_record binds each "done" node's evidence to a real, verified
# Agent spawn at record-time. graph_dispatch_complete must not trust that
# binding forever: it re-checks every terminal node's already-bound evidence
# again (spawn presence, notification status/result, and global id uniqueness)
# before allowing completion, so a transcript mutated after binding — or an
# evidence array hand-edited after the fact — cannot slip a graph to completion
# on stale trust. See graph_evidence_revalidate.sh's header for the rules.
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

LOOP="loop-fixture"
SETUP_FAILS=0

# Legitimately bind node N1 for $1 (session) with tool_use_id $2, leave the
# graph one step from completion, and echo the state path. Echoes nothing and
# returns non-zero if the bind itself did not happen.
bind_done_node() { # session tool_use_id
	local session="$1" tid="$2" cursor state rc
	claude_fixture::init "$PROJECTS" "$session"
	cursor=$(claude_fixture::cursor "$PROJECTS" "$session")
	claude_fixture::append_spawn "$PROJECTS" "$session" N1 wave-1 "$tid" >/dev/null
	append_notification "$PROJECTS" "$session" "$tid" completed
	state="$TMP/state_$session.json"
	jq -n --arg session "$session" --arg loop "$LOOP" --argjson c "$cursor" '
      {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
      | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
         graph:{nodes:{N1:$n},edges:[],joins:{},
                active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
                hard_stop:null}}' >"$state"
	graph_dispatch_record "$state" \
		"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
	rc=$?
	[ "$rc" -eq 0 ] || return 1
	# The bind must actually have written claude_agent evidence — otherwise a
	# later "refused" result would be measuring an empty graph, not a tamper.
	jq -e '.graph.nodes.N1.evidence[0].kind == "claude_agent"' "$state" >/dev/null 2>&1 || return 1
	jq '.graph.active_wave = null | .revision = 2' "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	write_valid_triple "$session" "$LOOP" 2 "$TMP/e_$session.json" "$TMP/p_$session.json" "$TMP/r_$session.json"
	printf '%s\n' "$state"
}

# graph_dispatch_complete against the triple bind_done_node wrote for $2.
# Merges stderr so callers can grep the refusal reason.
complete_with() { # state session
	graph_dispatch_complete "$1" --session "$2" \
		--evals "$TMP/e_$2.json" --proof "$TMP/p_$2.json" --retro "$TMP/r_$2.json" 2>&1
}

# Assert graph_dispatch_complete REFUSES $2 (a state) for a revalidation reason.
assert_refused_revalidation() { # label state session
	local label="$1" state="$2" session="$3" out
	if out=$(complete_with "$state" "$session"); then
		fail "$label" "completion SUCCEEDED on tampered evidence (bypass)"
	elif ! printf '%s' "$out" | grep -qi -- 'revalidat'; then
		fail "$label" "refused, but not for a revalidation reason; got: $out"
	else
		pass "$label"
	fi
}

# One forged shape: bind for real, overwrite N1.evidence, expect refusal.
check_forged_shape() { # label session_suffix jq_evidence_expr
	local label="$1" session="tamper-$2" tid="toolu_FORGED$2" state
	if ! state=$(bind_done_node "$session" "$tid"); then
		fail "$label" "setup: a legitimate bind did not happen, so the case proves nothing"
		SETUP_FAILS=$((SETUP_FAILS + 1))
		return
	fi
	jq --arg t "$tid" ".graph.nodes.N1.evidence = $3" "$state" >"$state.tmp" && mv "$state.tmp" "$state"
	assert_refused_revalidation "$label" "$state" "$session"
}

# --- a valid, untampered done node completes successfully ------------------
SESSION_VALID="session-complete-valid"
if state_valid=$(bind_done_node "$SESSION_VALID" toolu_COMPLETEVALID01) &&
	complete_with "$state_valid" "$SESSION_VALID" >/dev/null 2>&1; then
	pass "a valid untampered done node completes successfully"
else
	fail "a valid untampered done node completes successfully" \
		"completion did not succeed on a genuinely valid triple"
fi

# --- transcript mutated after bind: revalidation blocks completion ---------
# The transcript is wiped after binding, so N1's already-bound evidence can no
# longer be verified against the parent's own transcript.
SESSION_TAMPER="session-complete-tamper"
if state_tamper=$(bind_done_node "$SESSION_TAMPER" toolu_COMPLETETAMPER01); then
	: >"$(claude_fixture::transcript "$PROJECTS" "$SESSION_TAMPER")"
	assert_refused_revalidation "a bound node whose evidence is no longer valid blocks completion" \
		"$state_tamper" "$SESSION_TAMPER"
else
	fail "a bound node whose evidence is no longer valid blocks completion" \
		"setup: legitimate bind did not happen"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- transcript unparseable at revalidate-time: fails closed with a NAMED
# transcript reason ---
SESSION_UNREADABLE="session-complete-unreadable"
if state_unreadable=$(bind_done_node "$SESSION_UNREADABLE" toolu_COMPLETEUNREADABLE01); then
	printf 'not json at all\n{"type":"assistant"\n' \
		>"$(claude_fixture::transcript "$PROJECTS" "$SESSION_UNREADABLE")"
	if out=$(complete_with "$state_unreadable" "$SESSION_UNREADABLE"); then
		fail "an unparseable transcript at revalidate-time fails closed" \
			"completion succeeded with an unparseable transcript (fail-open)"
	elif ! printf '%s' "$out" | grep -qi -- 'transcript'; then
		fail "an unparseable transcript at revalidate-time fails closed" \
			"refused, but not with a transcript-naming reason; got: $out"
	else
		pass "an unparseable transcript at revalidate-time fails closed"
	fi
else
	fail "an unparseable transcript at revalidate-time fails closed" \
		"setup: legitimate bind did not happen"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- tamper-AFTER-bind: forged evidence shapes that used to fall out of the
# revalidation filter entirely ------------------------------------------------
#
# Pre-fix, bound evidence was selected with an exact
# `select(type == "object" and .kind == "claude_agent")`. Each shape below dodges
# that exact match, so the node read as "nothing bound" and completed. Each
# starts from a GENUINE bind (bind_done_node asserts it) and only then
# hand-edits the evidence — a case whose bind failed would pass for the wrong
# reason and prove nothing.
check_forged_shape "forged shape: array-wrapped evidence is refused" \
	arraywrap '[[{kind:"claude_agent",tool_use_id:$t}]]'
# An array-wrapped forgery reaches the same no-structured-entry branch a legacy
# free-text string does (neither is a top-level object), so that branch's
# message must stay shape-NEUTRAL. Pinned here because wording it as "free text"
# would misattribute this shape's cause — the exact defect the branch exists to
# avoid, and one no assertion grepping only for "revalidat" would catch.
if out=$(complete_with "$TMP/state_tamper-arraywrap.json" "tamper-arraywrap" 2>&1); then
	fail "the array-wrapped refusal message is not worded as free text" \
		"completion succeeded, so no message was produced"
elif printf '%s' "$out" | grep -qi -- 'free-text'; then
	fail "the array-wrapped refusal message is not worded as free text" \
		"an array-wrapped forgery was blamed on free text; got: $out"
else
	pass "the array-wrapped refusal message is not worded as free text"
fi
check_forged_shape "forged shape: evidence nested under a benign key is refused" \
	nested '[{note:"x",d:{kind:"claude_agent",tool_use_id:$t}}]'
check_forged_shape "forged shape: a trailing space in .kind is refused" \
	trailspace '[{kind:"claude_agent ",tool_use_id:$t}]'
check_forged_shape "forged shape: a partial spawn_ref-only entry is refused" \
	spawnref '[{attempt:1,wave_id:"wave-1",spawn_ref:$t}]'
check_forged_shape "forged shape: a homoglyph in .kind is refused" \
	homoglyph '[{kind:"claude_аgent",tool_use_id:$t}]'
check_forged_shape "forged shape: the bound shape as a JSON string is refused" \
	jsonstring '[("{\"kind\":\"claude_agent\",\"tool_use_id\":\"" + $t + "\"}")]'

# --- nested worker-reuse: one node cites another node's already-bound ids,
# buried under a benign key ---------------------------------------------------
# Pins the deep-select/shallow-READ asymmetry. These ids are REAL, so a
# revalidation reading fields recursively would find a valid tool_use_id and
# agent_id here and let the entry qualify. Reading only the top level refuses it.
SESSION_REUSE="tamper-nestedreuse"
if state_reuse=$(bind_done_node "$SESSION_REUSE" "toolu_NESTEDREUSE01"); then
	jq '.graph.nodes.N2 = {status:"done",outcome:"done",retry:{attempts:0,max:2},
        evidence:[{note:"carried",inner:(.graph.nodes.N1.evidence[0])}]}' \
		"$state_reuse" >"$state_reuse.tmp" && mv "$state_reuse.tmp" "$state_reuse"
	assert_refused_revalidation "nested reuse of another node's bound ids is refused" \
		"$state_reuse" "$SESSION_REUSE"
else
	fail "nested reuse of another node's bound ids is refused" "setup: legitimate bind did not happen"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- top-level duplicate reuse (regression guard) ----------------------------
# Already refused by the pre-fix global-uniqueness check. Kept so the
# field-extraction change cannot silently drop that existing protection.
SESSION_DUP="tamper-dupids"
if state_dup=$(bind_done_node "$SESSION_DUP" "toolu_DUPIDS01"); then
	jq '.graph.nodes.N2 = {status:"done",outcome:"done",retry:{attempts:0,max:2},
        evidence:[(.graph.nodes.N1.evidence[0])]}' \
		"$state_dup" >"$state_dup.tmp" && mv "$state_dup.tmp" "$state_dup"
	assert_refused_revalidation "a tool_use_id bound to two nodes is still refused" \
		"$state_dup" "$SESSION_DUP"
else
	fail "a tool_use_id bound to two nodes is still refused" "setup: legitimate bind did not happen"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- spawn record deleted, notification kept ---------------------------------
# Revalidation used to re-derive notification presence only, so deleting the
# Agent dispatch record while leaving the <task-notification> intact passed.
SESSION_NOSPAWN="tamper-nospawn"
if state_nospawn=$(bind_done_node "$SESSION_NOSPAWN" "toolu_NOSPAWN01"); then
	transcript_nospawn=$(claude_fixture::transcript "$PROJECTS" "$SESSION_NOSPAWN")
	# Strip ONLY the Agent tool_use dispatch record written by
	# claude_fixture::append_spawn; the notification record stays.
	grep -v '"name":"Agent"' "$transcript_nospawn" >"$transcript_nospawn.tmp" &&
		mv "$transcript_nospawn.tmp" "$transcript_nospawn"
	if grep -q '"name":"Agent"' "$transcript_nospawn"; then
		fail "a deleted spawn record with the notification kept is refused" \
			"setup: the Agent record was not actually stripped"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	elif ! grep -q 'task-notification' "$transcript_nospawn"; then
		fail "a deleted spawn record with the notification kept is refused" \
			"setup: the notification was stripped too, so this is not the case under test"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	else
		assert_refused_revalidation "a deleted spawn record with the notification kept is refused" \
			"$state_nospawn" "$SESSION_NOSPAWN"
	fi
else
	fail "a deleted spawn record with the notification kept is refused" "setup: legitimate bind did not happen"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- CROSS-NODE DONOR SPAWN ---------------------------------------------------
# Every other spawn-deletion case above deletes the ONLY spawn in its
# transcript, so a presence check asking merely "does this id exist anywhere"
# passes them all. This case is the one that shape cannot catch: N1 is done
# with its OWN dispatch record deleted, while N2 is left RUNNING (never
# done/skipped, so the global-uniqueness scan never sees it) holding a real,
# session-matched, notification-backed spawn. N1's evidence is forged to cite
# N2's ids. Pre-fix the id existed in the transcript and N1 completed.
#
# Both nodes are dispatched in the wave because graph_executor_graph_valid
# demands the set of "running" nodes equal the active wave's node set exactly;
# N2 is dropped back to a non-terminal state afterwards, which is what keeps
# it out of the done-or-skipped uniqueness scan.
SESSION_DONOR="tamper-donorspawn"
claude_fixture::init "$PROJECTS" "$SESSION_DONOR"
CURSOR_DONOR=$(claude_fixture::cursor "$PROJECTS" "$SESSION_DONOR")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_DONOR" N1 wave-1 toolu_DONORVICTIM01 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$SESSION_DONOR" N2 wave-1 toolu_DONORLIVE01 >/dev/null
append_notification "$PROJECTS" "$SESSION_DONOR" toolu_DONORVICTIM01 completed
# The donor spawn is fully legitimate: real record, session-matched, and its
# OWN completed notification. Without this the forged agent_id could not match
# a task_id and the case would refuse on the notification clause instead.
append_notification "$PROJECTS" "$SESSION_DONOR" toolu_DONORLIVE01 completed
state_donor="$TMP/state_donor.json"
jq -n --arg session "$SESSION_DONOR" --arg loop "$LOOP" --argjson c "$CURSOR_DONOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_donor"
graph_dispatch_record "$state_donor" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]},
                    N2:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_donor=$?
# N2 back to a non-terminal state, and its bound evidence dropped, so the
# uniqueness scan cannot see the donor ids on two nodes — the node_id clause
# is then the only thing that can refuse this case.
jq '.graph.active_wave = null | .revision = 2
  | .graph.nodes.N2.status = "pending" | .graph.nodes.N2.outcome = "pending"
  | .graph.nodes.N2.evidence = []' "$state_donor" >"$state_donor.tmp" &&
	mv "$state_donor.tmp" "$state_donor"
write_valid_triple "$SESSION_DONOR" "$LOOP" 2 "$TMP/e_$SESSION_DONOR.json" \
	"$TMP/p_$SESSION_DONOR.json" "$TMP/r_$SESSION_DONOR.json"
# Delete N1's own dispatch record, then forge N1's evidence onto the donor ids.
transcript_donor=$(claude_fixture::transcript "$PROJECTS" "$SESSION_DONOR")
grep -v 'toolu_DONORVICTIM01' "$transcript_donor" >"$transcript_donor.tmp" &&
	mv "$transcript_donor.tmp" "$transcript_donor"
jq '.graph.nodes.N1.evidence = [{kind:"claude_agent",attempt:1,wave_id:"wave-1",
      tool_use_id:"toolu_DONORLIVE01",agent_id:"toolu_DONORLIVE01",
      record_uuid:"uuid-toolu_DONORLIVE01",subagent_type:"coderails:loop-worker"}]' \
	"$state_donor" >"$state_donor.tmp" && mv "$state_donor.tmp" "$state_donor"
if [ "$rc_donor" -ne 0 ]; then
	fail "a done node citing another node's live spawn is refused" \
		"setup: the legitimate bind did not happen (rc=$rc_donor)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif ! jq -e '(.graph.nodes.N2.status | IN("done","skipped")) | not' "$state_donor" >/dev/null 2>&1; then
	fail "a done node citing another node's live spawn is refused" \
		"setup: the donor node is terminal, so uniqueness would catch this instead"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif grep -q 'toolu_DONORVICTIM01' "$transcript_donor"; then
	fail "a done node citing another node's live spawn is refused" \
		"setup: N1's own spawn record was not stripped"
	SETUP_FAILS=$((SETUP_FAILS + 1))
else
	assert_refused_revalidation "a done node citing another node's live spawn is refused" \
		"$state_donor" "$SESSION_DONOR"
fi

# --- cross-node donor spawn on a SKIPPED node ---------------------------------
# The done-node case above is refused by EITHER node_id clause (the presence
# scan's or the qualifying-entry check's), so neither is individually pinned by
# it — a mutation dropping just one still passes. A SKIPPED node never reaches
# the qualifying-entry check at all (that is done-only), so only the presence
# scan's node_id match can refuse this, which is what pins it.
SESSION_DONORSKIP="tamper-donorskip"
claude_fixture::init "$PROJECTS" "$SESSION_DONORSKIP"
CURSOR_DONORSKIP=$(claude_fixture::cursor "$PROJECTS" "$SESSION_DONORSKIP")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_DONORSKIP" N1 wave-1 toolu_DSKDONE01 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$SESSION_DONORSKIP" N2 wave-1 toolu_DSKCARRY01 >/dev/null
append_notification "$PROJECTS" "$SESSION_DONORSKIP" toolu_DSKDONE01 completed
state_donorskip="$TMP/state_donorskip.json"
jq -n --arg session "$SESSION_DONORSKIP" --arg loop "$LOOP" --argjson c "$CURSOR_DONORSKIP" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_donorskip"
graph_dispatch_record "$state_donorskip" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]},
                    N2:{outcome:"failed",evidence:[]}}}')" >/dev/null 2>&1
rc_donorskip=$?
jq '.graph.active_wave = null | .revision = 2
  | .graph.nodes.N2.status = "skipped" | .graph.nodes.N2.outcome = "skipped"' \
	"$state_donorskip" >"$state_donorskip.tmp" && mv "$state_donorskip.tmp" "$state_donorskip"
write_valid_triple "$SESSION_DONORSKIP" "$LOOP" 2 "$TMP/e_$SESSION_DONORSKIP.json" \
	"$TMP/p_$SESSION_DONORSKIP.json" "$TMP/r_$SESSION_DONORSKIP.json"
# Delete the SKIPPED node's own spawn, then re-point its carried entry at a
# spawn that genuinely exists but belongs to N1. No agent_id is involved, so
# the uniqueness scan sees one tool_use_id on two nodes... which it WOULD catch
# — so N1's own entry is dropped, leaving the donor id bound only on N2.
transcript_donorskip=$(claude_fixture::transcript "$PROJECTS" "$SESSION_DONORSKIP")
grep -v 'toolu_DSKCARRY01' "$transcript_donorskip" >"$transcript_donorskip.tmp" &&
	mv "$transcript_donorskip.tmp" "$transcript_donorskip"
jq '.graph.nodes.N2.evidence = [(.graph.nodes.N2.evidence[0]
      | .tool_use_id = "toolu_DSKDONE01" | .record_uuid = "uuid-toolu_DSKDONE01")]
  | .graph.nodes.N1.status = "skipped" | .graph.nodes.N1.outcome = "skipped"
  | .graph.nodes.N1.evidence = []' \
	"$state_donorskip" >"$state_donorskip.tmp" && mv "$state_donorskip.tmp" "$state_donorskip"
if [ "$rc_donorskip" -ne 0 ] ||
	! jq -e '.graph.nodes.N2.evidence[0].tool_use_id == "toolu_DSKDONE01"
             and ((.graph.nodes.N2.evidence[0] | has("agent_id")) | not)' \
		"$state_donorskip" >/dev/null 2>&1; then
	fail "a skipped node citing another node's spawn is refused" \
		"setup: the bind or the re-point did not happen (rc=$rc_donorskip)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
else
	assert_refused_revalidation "a skipped node citing another node's spawn is refused" \
		"$state_donorskip" "$SESSION_DONORSKIP"
fi

# --- a SURVIVING session-mismatched spawn row ---------------------------------
# Distinct from deleting the record: the dispatch record stays, but the
# envelope's OWN session_id is mutated to disagree with the session. The
# record's .sessionId is left alone deliberately — mutating THAT drops the row
# from graph_evidence_spawns entirely, which would measure absence rather than
# the session_mismatch exclusion under test.
SESSION_MISMATCH="tamper-sessionmismatch"
if state_mismatch=$(bind_done_node "$SESSION_MISMATCH" "toolu_MISMATCH01"); then
	transcript_mismatch=$(claude_fixture::transcript "$PROJECTS" "$SESSION_MISMATCH")
	# Guarded on content being an ARRAY: a notification record carries
	# .message.content as a plain string, and indexing that aborts the parse.
	jq -c 'if ((.message.content | type) == "array")
	          and ((.message.content[0].name? // "") == "Agent")
	       then .message.content[0].input.prompt =
	         ((.message.content[0].input.prompt | split("\n")[0]
	           | ltrimstr("CODERAILS_GRAPH_DISPATCH=") | fromjson
	           | .session_id = "some-other-session"
	           | "CODERAILS_GRAPH_DISPATCH=" + tojson) + "\nwork unit body")
	       else . end' "$transcript_mismatch" >"$transcript_mismatch.tmp" &&
		mv "$transcript_mismatch.tmp" "$transcript_mismatch"
	spawn_row_mismatch=$(graph_evidence_spawns "$transcript_mismatch" "$SESSION_MISMATCH")
	if ! printf '%s' "$spawn_row_mismatch" | jq -e 'select(.session_mismatch == true)' >/dev/null 2>&1; then
		fail "a surviving session-mismatched spawn row is refused" \
			"setup: the row is not session_mismatch:true; got: $spawn_row_mismatch"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	else
		assert_refused_revalidation "a surviving session-mismatched spawn row is refused" \
			"$state_mismatch" "$SESSION_MISMATCH"
	fi
else
	fail "a surviving session-mismatched spawn row is refused" "setup: legitimate bind did not happen"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- a teammate_spawned spawn cited post-bind ---------------------------------
# graph_evidence_bind.sh refuses to bind a DONE node against a mailbox/teammate
# dispatch (line 342). Revalidation must make the same demand, or a post-bind
# hand-edit re-points a done node at a teammate_spawned spawn it could never
# have bound to. BOTH spawns belong to N1 (bind's own comment documents
# fan-out as legitimate) so the node_id clause cannot refuse this case for the
# wrong reason — only the dispatch_status clause can.
SESSION_TEAM="tamper-teammate"
claude_fixture::init "$PROJECTS" "$SESSION_TEAM"
CURSOR_TEAM=$(claude_fixture::cursor "$PROJECTS" "$SESSION_TEAM")
# The mailbox spawn is written FIRST: bind takes the LAST free candidate
# ($free | .[-1]), and binding a done node against a teammate_spawned spawn is
# exactly what bind refuses — so the legitimate async_launched one must be last
# or the setup bind fails and the case proves nothing.
claude_fixture::append_spawn "$PROJECTS" "$SESSION_TEAM" N1 wave-1 toolu_TEAMMAIL01 >/dev/null
claude_fixture::append_dispatch_status "$PROJECTS" "$SESSION_TEAM" toolu_TEAMMAIL01 teammate_spawned
claude_fixture::append_spawn "$PROJECTS" "$SESSION_TEAM" N1 wave-1 toolu_TEAMREAL01 >/dev/null
claude_fixture::append_dispatch_status "$PROJECTS" "$SESSION_TEAM" toolu_TEAMREAL01 async_launched
append_notification "$PROJECTS" "$SESSION_TEAM" toolu_TEAMREAL01 completed
append_notification "$PROJECTS" "$SESSION_TEAM" toolu_TEAMMAIL01 completed
state_team="$TMP/state_team.json"
jq -n --arg session "$SESSION_TEAM" --arg loop "$LOOP" --argjson c "$CURSOR_TEAM" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
   graph:{nodes:{N1:{status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]}},
          edges:[],joins:{},
          active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
          hard_stop:null}}' >"$state_team"
graph_dispatch_record "$state_team" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_team=$?
jq '.graph.active_wave = null | .revision = 2' "$state_team" >"$state_team.tmp" && mv "$state_team.tmp" "$state_team"
write_valid_triple "$SESSION_TEAM" "$LOOP" 2 "$TMP/e_$SESSION_TEAM.json" \
	"$TMP/p_$SESSION_TEAM.json" "$TMP/r_$SESSION_TEAM.json"
# Re-point the bound entry at the teammate_spawned spawn, ids consistent.
jq '.graph.nodes.N1.evidence = [(.graph.nodes.N1.evidence[0]
      | .tool_use_id = "toolu_TEAMMAIL01" | .agent_id = "toolu_TEAMMAIL01"
      | .record_uuid = "uuid-toolu_TEAMMAIL01")]' \
	"$state_team" >"$state_team.tmp" && mv "$state_team.tmp" "$state_team"
if [ "$rc_team" -ne 0 ] ||
	! jq -e '.graph.nodes.N1.evidence[0].tool_use_id == "toolu_TEAMMAIL01"' "$state_team" >/dev/null 2>&1; then
	fail "a done node re-pointed at a teammate_spawned spawn is refused" \
		"setup: the bind or the re-point did not happen (rc=$rc_team)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif out=$(complete_with "$state_team" "$SESSION_TEAM"); then
	fail "a done node re-pointed at a teammate_spawned spawn is refused" \
		"completion SUCCEEDED on a mailbox-dispatched spawn (bypass)"
# Wording-specific on BOTH sides, not assert_refused_revalidation's bare
# grep for 'revalidat' — that helper passes on ANY revalidation refusal,
# which is exactly how this case shipped refusing for the WRONG reason.
# The notification for toolu_TEAMMAIL01 exists and reports completed, so
# blaming notification evidence sends the operator hunting a non-problem;
# only the dispatch_status clause can refuse this case.
elif ! printf '%s' "$out" | grep -qi -- 'mailbox/teammate'; then
	fail "a done node re-pointed at a teammate_spawned spawn is refused" \
		"refused, but the reason did not name the mailbox/teammate cause; got: $out"
elif printf '%s' "$out" | grep -qi -- 'no still-valid completed-notification'; then
	fail "a done node re-pointed at a teammate_spawned spawn is refused" \
		"refused with the generic notification-evidence message, misnaming the cause; got: $out"
else
	pass "a done node re-pointed at a teammate_spawned spawn is refused"
fi

# --- a multi-attempt (retried) node still completes ---------------------------
# The spawn-presence demand applies per ENTRY, and a retried node carries an
# EXTRA entry from its failed attempt (a tool_use_id with no agent_id). This
# pins that such a node still completes on an intact transcript — if it did
# not, every node that ever retried before finishing would deadlock, which is
# the exact failure the per-entry keying exists to avoid.
SESSION_RETRY="complete-retry"
claude_fixture::init "$PROJECTS" "$SESSION_RETRY"
CURSOR_R1=$(claude_fixture::cursor "$PROJECTS" "$SESSION_RETRY")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_RETRY" N1 wave-1 toolu_RETRYATT1 >/dev/null
state_retry="$TMP/state_retry.json"
jq -n --arg session "$SESSION_RETRY" --arg loop "$LOOP" --argjson c "$CURSOR_R1" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
   graph:{nodes:{N1:{status:"running",outcome:"running",retry:{attempts:0,max:3},evidence:[]}},
          edges:[],joins:{},
          active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
          hard_stop:null}}' >"$state_retry"
# Attempt 1 fails: binds a spawn reference with NO agent_id (no notification).
graph_dispatch_record "$state_retry" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"failed",evidence:[]}}}')" >/dev/null 2>&1
rc_retry1=$?
# Attempt 2 succeeds: binds a second spawn WITH an agent_id.
CURSOR_R2=$(claude_fixture::cursor "$PROJECTS" "$SESSION_RETRY")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_RETRY" N1 wave-2 toolu_RETRYATT2 >/dev/null
append_notification "$PROJECTS" "$SESSION_RETRY" toolu_RETRYATT2 completed
jq --argjson c "$CURSOR_R2" '.revision = 2
  | .graph.nodes.N1.status = "running" | .graph.nodes.N1.outcome = "running"
  | .graph.active_wave = {wave_id:"wave-2",revision:2,nodes:["N1"],transcript_cursor:$c}' \
	"$state_retry" >"$state_retry.tmp" && mv "$state_retry.tmp" "$state_retry"
graph_dispatch_record "$state_retry" \
	"$(jq -cn '{wave_id:"wave-2",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_retry2=$?
jq '.graph.active_wave = null | .revision = 3' "$state_retry" >"$state_retry.tmp" && mv "$state_retry.tmp" "$state_retry"
write_valid_triple "$SESSION_RETRY" "$LOOP" 3 "$TMP/e_$SESSION_RETRY.json" \
	"$TMP/p_$SESSION_RETRY.json" "$TMP/r_$SESSION_RETRY.json"
# Both attempts must actually be on the node, or this proves nothing.
if [ "$rc_retry1" -ne 0 ] || [ "$rc_retry2" -ne 0 ] ||
	! jq -e '(.graph.nodes.N1.evidence | length) == 2
             and (.graph.nodes.N1.evidence[0] | has("agent_id") | not)
             and (.graph.nodes.N1.evidence[1].agent_id != null)' "$state_retry" >/dev/null 2>&1; then
	fail "a retried node with a carried-forward attempt entry still completes" \
		"setup: the two-attempt evidence trail was not built (rc1=$rc_retry1 rc2=$rc_retry2)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif complete_with "$state_retry" "$SESSION_RETRY" >/dev/null 2>&1; then
	pass "a retried node with a carried-forward attempt entry still completes"
	# Deletion arm, mirroring the skipped-node one below: delete the
	# CARRIED-FORWARD attempt's own spawn record (not the successful one) and
	# the graph must be refused. Without this the widening's claim that a
	# carried-forward entry is genuinely re-checked rests on the accept arm
	# alone, which passes whether or not the demand is actually made.
	transcript_retry=$(claude_fixture::transcript "$PROJECTS" "$SESSION_RETRY")
	grep -v 'toolu_RETRYATT1' "$transcript_retry" >"$transcript_retry.tmp" &&
		mv "$transcript_retry.tmp" "$transcript_retry"
	if grep -q 'toolu_RETRYATT2' "$transcript_retry"; then
		if out=$(complete_with "$state_retry" "$SESSION_RETRY"); then
			fail "a retried node whose carried-forward spawn is deleted is refused" \
				"completion SUCCEEDED with the failed attempt's spawn gone"
		elif ! printf '%s' "$out" | grep -q -- 'toolu_RETRYATT1'; then
			fail "a retried node whose carried-forward spawn is deleted is refused" \
				"refused, but did not name the deleted attempt's spawn; got: $out"
		else
			pass "a retried node whose carried-forward spawn is deleted is refused"
		fi
	else
		fail "a retried node whose carried-forward spawn is deleted is refused" \
			"setup: the successful attempt's spawn was stripped too"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	fi
else
	fail "a retried node with a carried-forward attempt entry still completes" \
		"the per-entry spawn demand deadlocked a legitimately retried node"
fi

# --- a SKIPPED node carrying bound evidence -----------------------------------
# $bound selects done-OR-skipped, so the spawn demand reaches a skipped node's
# carried evidence too — a path no suite exercised before. Both arms are pinned
# here: an intact transcript still completes, and deleting the SKIPPED node's
# own spawn record is refused (naming that node), so the arm cannot silently
# rot into either a deadlock or a hole.
#
# The skipped node's spawn is ALSO marked teammate_spawned, which makes this the
# ACCEPT arm for the dispatch_status asymmetry: graph_evidence_revalidate.sh
# deliberately does NOT filter dispatch_status in its all-entries spawn-presence
# scan, precisely so a legitimately mailbox-dispatched skipped node (or retry
# carry-forward) is not deadlocked — the demand is made only on a DONE node's
# qualifying entry, mirroring where bind makes it. Until now that was asserted
# in prose only; this pins it. N2 reports "failed", so bind takes its non-done
# branch and never reaches the teammate_spawned refusal, and the done-only
# terminal recheck never reaches N2 at all.
SESSION_SKIP="complete-skipnode"
claude_fixture::init "$PROJECTS" "$SESSION_SKIP"
CURSOR_SKIP=$(claude_fixture::cursor "$PROJECTS" "$SESSION_SKIP")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_SKIP" N1 wave-1 toolu_SKIPDONE01 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$SESSION_SKIP" N2 wave-1 toolu_SKIPCARRY01 >/dev/null
claude_fixture::append_dispatch_status "$PROJECTS" "$SESSION_SKIP" toolu_SKIPCARRY01 teammate_spawned
append_notification "$PROJECTS" "$SESSION_SKIP" toolu_SKIPDONE01 completed
state_skip="$TMP/state_skip.json"
jq -n --arg session "$SESSION_SKIP" --arg loop "$LOOP" --argjson c "$CURSOR_SKIP" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_skip"
# N2 reports "failed", so the non-done bind branch writes claude_agent evidence
# with NO agent_id; it is then marked skipped, the shape under test.
graph_dispatch_record "$state_skip" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]},N2:{outcome:"failed",evidence:[]}}}')" \
	>/dev/null 2>&1
rc_skip_record=$?
jq '.graph.active_wave = null | .revision = 2
  | .graph.nodes.N2.status = "skipped" | .graph.nodes.N2.outcome = "skipped"' \
	"$state_skip" >"$state_skip.tmp" && mv "$state_skip.tmp" "$state_skip"
write_valid_triple "$SESSION_SKIP" "$LOOP" 2 "$TMP/e_$SESSION_SKIP.json" \
	"$TMP/p_$SESSION_SKIP.json" "$TMP/r_$SESSION_SKIP.json"
if [ "$rc_skip_record" -ne 0 ] ||
	! jq -e '.graph.nodes.N2.evidence[0].kind == "claude_agent"
             and (.graph.nodes.N2.evidence[0] | has("agent_id") | not)' \
		"$state_skip" >/dev/null 2>&1; then
	fail "a skipped node carrying bound evidence still completes" \
		"setup: the skipped node did not carry claude_agent evidence (rc=$rc_skip_record)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif complete_with "$state_skip" "$SESSION_SKIP" >/dev/null 2>&1; then
	pass "a skipped node carrying bound evidence still completes"
	# Now delete the SKIPPED node's own spawn record.
	transcript_skip=$(claude_fixture::transcript "$PROJECTS" "$SESSION_SKIP")
	grep -v 'toolu_SKIPCARRY01' "$transcript_skip" >"$transcript_skip.tmp" &&
		mv "$transcript_skip.tmp" "$transcript_skip"
	if out=$(complete_with "$state_skip" "$SESSION_SKIP"); then
		fail "a skipped node whose spawn record is deleted is refused" \
			"completion SUCCEEDED with the skipped node's spawn gone"
	elif ! printf '%s' "$out" | grep -q -- 'N2'; then
		fail "a skipped node whose spawn record is deleted is refused" \
			"refused, but did not name the skipped node; got: $out"
	else
		pass "a skipped node whose spawn record is deleted is refused"
	fi
else
	fail "a skipped node carrying bound evidence still completes" \
		"the spawn demand deadlocked a legitimately skipped, mailbox-dispatched node"
fi

# --- the legacy/cursorless path must still complete --------------------------
# A "done" node whose evidence was never bound to a transcript (a plain string)
# has nothing to re-verify, and revalidation must stay additive rather than
# becoming a new requirement for graphs that were never asked to bind.
SESSION_LEGACY="complete-legacy"
state_legacy="$TMP/state_legacy.json"
jq -n --arg session "$SESSION_LEGACY" --arg loop "$LOOP" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:2,status:"in-progress",
   graph:{nodes:{N1:{status:"done",outcome:"done",retry:{attempts:0,max:2},
                     evidence:["did the work"]}},
          edges:[],joins:{},active_wave:null,hard_stop:null}}' >"$state_legacy"
write_valid_triple "$SESSION_LEGACY" "$LOOP" 2 "$TMP/e_$SESSION_LEGACY.json" \
	"$TMP/p_$SESSION_LEGACY.json" "$TMP/r_$SESSION_LEGACY.json"
if complete_with "$state_legacy" "$SESSION_LEGACY" >/dev/null 2>&1; then
	pass "a legacy done node with unbound string evidence still completes"
else
	fail "a legacy done node with unbound string evidence still completes" \
		"the widened selector regressed the cursorless/legacy completion path"
fi

# --- a legacy STRING entry that merely mentions provenance text ---------------
# Disclosed widening, not a fix: looks_provenance scans string leaves (that is
# what drags the JSON-string forgery in), so a free-text legacy entry
# mentioning toolu_ selects into the bound set, normalises to no ids, so its
# owning node can never produce a qualifying entry. Refused — and the
# refusal must NAME that cause rather than blaming notification evidence, or
# an operator debugs the wrong thing. The transcript must exist and resolve,
# or the refusal comes from the transcript resolver instead.
SESSION_STRPROV="complete-stringprovenance"
claude_fixture::init "$PROJECTS" "$SESSION_STRPROV"
claude_fixture::append_noise "$PROJECTS" "$SESSION_STRPROV"
state_strprov="$TMP/state_strprov.json"
jq -n --arg session "$SESSION_STRPROV" --arg loop "$LOOP" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:2,status:"in-progress",
   graph:{nodes:{N1:{status:"done",outcome:"done",retry:{attempts:0,max:2},
                     evidence:["worker finished, dispatch was toolu_ABC123"]}},
          edges:[],joins:{},active_wave:null,hard_stop:null}}' >"$state_strprov"
write_valid_triple "$SESSION_STRPROV" "$LOOP" 2 "$TMP/e_$SESSION_STRPROV.json" \
	"$TMP/p_$SESSION_STRPROV.json" "$TMP/r_$SESSION_STRPROV.json"
if out=$(complete_with "$state_strprov" "$SESSION_STRPROV"); then
	fail "a legacy string mentioning provenance text is refused by name" \
		"completion succeeded; the disclosed widening is not what actually happens"
elif ! printf '%s' "$out" | grep -qi -- 'no structured bound entry'; then
	fail "a legacy string mentioning provenance text is refused by name" \
		"refused, but the reason did not name the unstructured-entry cause; got: $out"
else
	pass "a legacy string mentioning provenance text is refused by name"
fi

# --- WAVE-HISTORY: a SINGLE done node whose evidence is emptied, with no
# surviving sibling evidence anywhere in the graph ---------------------------
# This shape used to be undetectable by this mechanism (the comment this
# block replaces explained why: no surviving sibling entry could prove the
# wave ever bound anything real, making it information-theoretically
# identical to a legitimately cursorless wave). .graph.wave_history closes it:
# graph_dispatch_begin_wave durably records the wave's own {cursor, nodes} the
# moment it opens, and that record survives completion's own
# `.graph.active_wave = null`, so it no longer needs a surviving sibling to
# prove the wave was real. Driven through the REAL graph_dispatch_begin_wave
# and graph_dispatch_record — not a hand-built progress.json — so
# .graph.wave_history is written by the actual production write path.
new_wave_state() { # session node_id -> writes+prints a fresh single-node progress.json path
	local session="$1" node="$2" state="$TMP/state_wavehist_$1.json"
	jq -n --arg session "$session" --arg loop "$LOOP" --arg node "$node" '
      {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
       graph:{nodes:{($node):{status:"pending",outcome:"pending",retry:{attempts:0,max:2},evidence:[]}},
              edges:[],joins:{},active_wave:null,hard_stop:null}}' >"$state"
	printf '%s\n' "$state"
}

# Drive a genuine cursored wave-open + dispatch + record for a single node
# N1, via the REAL production functions, and return the resulting revision on
# stdout — or nothing, non-zero, if any real step failed.
drive_wavehist_bind() { # session outcome(done|failed) -> echoes "revision tool_use_id" on success
	local session="$1" outcome="$2"
	local tid="toolu_WAVEHIST_${session//[^A-Za-z0-9]/_}" state
	claude_fixture::init "$PROJECTS" "$session"
	claude_fixture::append_noise "$PROJECTS" "$session"
	state=$(new_wave_state "$session" N1)
	graph_dispatch_begin_wave "$state" >/dev/null 2>&1 || return 1
	local wave_id
	wave_id=$(jq -r '.graph.active_wave.wave_id' "$state") || return 1
	[ -n "$wave_id" ] && [ "$wave_id" != "null" ] || return 1
	claude_fixture::append_spawn "$PROJECTS" "$session" N1 "$wave_id" "$tid" >/dev/null
	[ "$outcome" = "done" ] && append_notification "$PROJECTS" "$session" "$tid" completed
	graph_dispatch_record "$state" \
		"$(jq -cn --arg w "$wave_id" --arg o "$outcome" '{wave_id:$w,results:{N1:{outcome:$o,evidence:[]}}}')" \
		>/dev/null 2>&1 || return 1
	local revision
	revision=$(jq -r '.revision' "$state") || return 1
	printf '%s %s %s\n' "$state" "$revision" "$tid"
}

# --- (a) a DONE node with a real cursored dispatch, all evidence in its wave
# deleted, no surviving sibling anywhere — must now REFUSE ------------------
SESSION_WAVEHIST_DONE="wavehist-done"
if out=$(drive_wavehist_bind "$SESSION_WAVEHIST_DONE" "done"); then
	read -r wh_state wh_revision wh_tid <<<"$out"
	if ! jq -e '.graph.nodes.N1.evidence[0].kind == "claude_agent"
	             and (.graph.wave_history | keys | length) > 0' "$wh_state" >/dev/null 2>&1; then
		fail "a done node's evidence-wiped wave with no sibling is now refused (wave_history)" \
			"setup: bind did not write claude_agent evidence, or wave_history is empty"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	else
		write_valid_triple "$SESSION_WAVEHIST_DONE" "$LOOP" "$wh_revision" \
			"$TMP/e_$SESSION_WAVEHIST_DONE.json" "$TMP/p_$SESSION_WAVEHIST_DONE.json" "$TMP/r_$SESSION_WAVEHIST_DONE.json"
		jq '.graph.nodes.N1.evidence = []' "$wh_state" >"$wh_state.tmp" && mv "$wh_state.tmp" "$wh_state"
		assert_refused_revalidation "a done node's evidence-wiped wave with no sibling is now refused (wave_history)" \
			"$wh_state" "$SESSION_WAVEHIST_DONE"
	fi
else
	fail "a done node's evidence-wiped wave with no sibling is now refused (wave_history)" \
		"setup: the real begin_wave/record path did not bind legitimately"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- (b) same shape, but the node is SKIPPED instead of done ---------------
SESSION_WAVEHIST_SKIP="wavehist-skip"
if out=$(drive_wavehist_bind "$SESSION_WAVEHIST_SKIP" failed); then
	read -r wh_state wh_revision wh_tid <<<"$out"
	jq '.graph.nodes.N1.status = "skipped" | .graph.nodes.N1.outcome = "skipped"' \
		"$wh_state" >"$wh_state.tmp" && mv "$wh_state.tmp" "$wh_state"
	if ! jq -e '.graph.nodes.N1.evidence[0].kind == "claude_agent"
	             and (.graph.wave_history | keys | length) > 0' "$wh_state" >/dev/null 2>&1; then
		fail "a skipped node's evidence-wiped wave with no sibling is now refused (wave_history)" \
			"setup: bind did not carry claude_agent evidence, or wave_history is empty"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	else
		write_valid_triple "$SESSION_WAVEHIST_SKIP" "$LOOP" "$wh_revision" \
			"$TMP/e_$SESSION_WAVEHIST_SKIP.json" "$TMP/p_$SESSION_WAVEHIST_SKIP.json" "$TMP/r_$SESSION_WAVEHIST_SKIP.json"
		jq '.graph.nodes.N1.evidence = []' "$wh_state" >"$wh_state.tmp" && mv "$wh_state.tmp" "$wh_state"
		assert_refused_revalidation "a skipped node's evidence-wiped wave with no sibling is now refused (wave_history)" \
			"$wh_state" "$SESSION_WAVEHIST_SKIP"
	fi
else
	fail "a skipped node's evidence-wiped wave with no sibling is now refused (wave_history)" \
		"setup: the real begin_wave/record path did not bind legitimately"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- (c) NEGATIVE CONTROL: same shape, but wave_history is ABSENT (a pre-fix
# loop, or a genuinely cursorless wave) — must still PASS, exactly as before -
# Built by taking the SAME real bind as (a) and then stripping wave_history,
# which honestly simulates "this loop predates the fix" without fighting the
# fact that even an empty transcript yields a real numeric cursor (0) through
# the real begin_wave path, which would make a hand-built cursorless fixture
# here dishonest.
SESSION_WAVEHIST_NOHISTORY="wavehist-nohistory"
if out=$(drive_wavehist_bind "$SESSION_WAVEHIST_NOHISTORY" "done"); then
	read -r wh_state wh_revision wh_tid <<<"$out"
	if ! jq -e '.graph.nodes.N1.evidence[0].kind == "claude_agent"
	             and (.graph.wave_history | keys | length) > 0' "$wh_state" >/dev/null 2>&1; then
		fail "a done node with no wave_history entry still completes (negative control)" \
			"setup: bind did not write claude_agent evidence, or wave_history is empty"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	else
		write_valid_triple "$SESSION_WAVEHIST_NOHISTORY" "$LOOP" "$wh_revision" \
			"$TMP/e_$SESSION_WAVEHIST_NOHISTORY.json" "$TMP/p_$SESSION_WAVEHIST_NOHISTORY.json" \
			"$TMP/r_$SESSION_WAVEHIST_NOHISTORY.json"
		jq '.graph.nodes.N1.evidence = [] | del(.graph.wave_history)' \
			"$wh_state" >"$wh_state.tmp" && mv "$wh_state.tmp" "$wh_state"
		if complete_with "$wh_state" "$SESSION_WAVEHIST_NOHISTORY" >/dev/null 2>&1; then
			pass "a done node with no wave_history entry still completes (negative control)"
		else
			fail "a done node with no wave_history entry still completes (negative control)" \
				"completion was refused even though wave_history is absent (pre-fix/cursorless simulation regressed)"
		fi
	fi
else
	fail "a done node with no wave_history entry still completes (negative control)" \
		"setup: the real begin_wave/record path did not bind legitimately"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- (d) a stray/replayed dispatch envelope naming a node NOT in the wave's
# recorded node list must NOT be wrongly demanded ----------------------------
# The pre-existing SIBLING-anchored path ($dispatched_by_sibling, unmodified)
# already demands evidence for any node whose spawn row shares a wave_id with
# a wave that has SOME surviving bound entry ($bound_waves). To isolate the
# NEW wave_history-anchored path specifically, the stray row's wave_id must
# have a wave_history entry but must NOT be in $bound_waves — i.e. N1's own
# spawn/notification records (the only thing that could put wave-2 into
# $bound_waves) are stripped from the transcript entirely, and N1's evidence
# is emptied too, so wave-2 is demanded ONLY via wave_history, never via a
# surviving sibling. (N1 itself, now carrying no evidence and no transcript
# spawn, is demanded by neither path — the same accepted, disclosed limit
# this file's header already documents; this fixture is not testing N1.)
SESSION_WAVEHIST_STRAY="wavehist-stray"
if out=$(drive_wavehist_bind "$SESSION_WAVEHIST_STRAY" "done"); then
	read -r wh_state wh_revision wh_tid <<<"$out"
	wave_id_stray=$(jq -r '.graph.wave_history | keys[0]' "$wh_state")
	transcript_stray=$(claude_fixture::transcript "$PROJECTS" "$SESSION_WAVEHIST_STRAY")
	# Strip N1's own spawn AND notification records (both carry $wh_tid) so
	# wave-2 has zero surviving spawn rows -> wave-2 stays OUT of $bound_waves.
	grep -v "$wh_tid" "$transcript_stray" >"$transcript_stray.tmp" && mv "$transcript_stray.tmp" "$transcript_stray"
	jq '.graph.nodes.N1.evidence = []' "$wh_state" >"$wh_state.tmp" && mv "$wh_state.tmp" "$wh_state"
	# N2: a second, real graph node, dispatched and completed in its OWN
	# separate wave via the REAL graph_dispatch_record path but with its
	# active_wave HAND-WRITTEN (bypassing graph_dispatch_begin_wave, so N2's
	# own wave never gets a wave_history entry — load-bearing: it is what
	# keeps this fixture about N2's stray row citing wave-2, not about N2's
	# own wave). wave_id must literally be "wave-<current revision>" —
	# graph_executor_graph_valid's own contract on .graph.active_wave.
	jq '.graph.nodes.N2 = {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]}
      | .graph.active_wave = {wave_id:("wave-" + (.revision|tostring)),revision:.revision,nodes:["N2"]}' \
		"$wh_state" >"$wh_state.tmp" && mv "$wh_state.tmp" "$wh_state"
	wave_id_n2=$(jq -r '.graph.active_wave.wave_id' "$wh_state")
	graph_dispatch_record "$wh_state" \
		"$(jq -cn --arg w "$wave_id_n2" '{wave_id:$w,results:{N2:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
	rc_stray_n2=$?
	wh_revision=$(jq -r '.revision' "$wh_state")
	# Plant a stray spawn row citing wave-2's OWN wave_id (the wave
	# wave_history recorded for N1 alone) but naming N2 — a node wave-2's own
	# recorded node list never included. Appended after wave-2's own cursor,
	# so the cursor clause alone cannot explain a refusal here; only the
	# node-list clause can.
	claude_fixture::append_spawn "$PROJECTS" "$SESSION_WAVEHIST_STRAY" N2 "$wave_id_stray" toolu_STRAYNODE01 >/dev/null
	if [ "$rc_stray_n2" -ne 0 ] ||
		! jq -e '.graph.nodes.N2.status == "done" and .graph.nodes.N2.evidence == []
                 and (.graph.wave_history[$w].nodes | index("N1")) != null' --arg w "$wave_id_stray" \
			"$wh_state" >/dev/null 2>&1 ||
		grep -q "$wh_tid" "$transcript_stray"; then
		fail "a stray dispatch envelope naming a node outside the wave's recorded list is not wrongly demanded" \
			"setup: N2 did not reach the expected state, or N1's own spawn/notification survived stripping (rc_n2=$rc_stray_n2)"
		SETUP_FAILS=$((SETUP_FAILS + 1))
	else
		write_valid_triple "$SESSION_WAVEHIST_STRAY" "$LOOP" "$wh_revision" \
			"$TMP/e_$SESSION_WAVEHIST_STRAY.json" "$TMP/p_$SESSION_WAVEHIST_STRAY.json" \
			"$TMP/r_$SESSION_WAVEHIST_STRAY.json"
		if complete_with "$wh_state" "$SESSION_WAVEHIST_STRAY" >/dev/null 2>&1; then
			pass "a stray dispatch envelope naming a node outside the wave's recorded list is not wrongly demanded"
		else
			fail "a stray dispatch envelope naming a node outside the wave's recorded list is not wrongly demanded" \
				"completion was refused; N2 was wrongly demanded evidence from wave-2's stray row despite never being in wave-2's own node list"
		fi
	fi
else
	fail "a stray dispatch envelope naming a node outside the wave's recorded list is not wrongly demanded" \
		"setup: the real begin_wave/record path did not bind legitimately"
	SETUP_FAILS=$((SETUP_FAILS + 1))
fi

# --- (extra, cursor discrimination) a spawn row forward-forged BEFORE its
# claimed wave's own cursor was recorded must NOT be wrongly demanded --------
# A spawn row for N1 is planted in the transcript BEFORE graph_dispatch_begin_
# wave ever runs (so its .line is <= the wave's own recorded cursor) but
# citing the wave_id that begin_wave is about to mint — exactly the forgery
# the `$r.line > $wh[$r.wave_id].cursor` clause exists to reject: an
# orchestrator writing a dispatch prompt for a wave that does not exist yet.
# N1 is then completed via a real, SEPARATE cursorless bind (never through the
# wave the pre-cursor row claims), so its evidence is legitimately empty. If
# the cursor clause were missing, this pre-cursor row would still satisfy
# `$wh[$r.wave_id] != null` and the node-list clause (N1 IS the wave's own
# recorded node), wrongly pulling N1 into $dispatched_by_history and refusing
# a graph that never actually bound N1 in that wave.
SESSION_WAVEHIST_PRECURSOR="wavehist-precursor"
claude_fixture::init "$PROJECTS" "$SESSION_WAVEHIST_PRECURSOR"
# The forged row: appended FIRST, before any noise or begin_wave call, so its
# line number sits at or before whatever cursor begin_wave is about to record.
claude_fixture::append_spawn "$PROJECTS" "$SESSION_WAVEHIST_PRECURSOR" N1 wave-2 toolu_PRECURSOR01 >/dev/null
claude_fixture::append_noise "$PROJECTS" "$SESSION_WAVEHIST_PRECURSOR"
state_precursor=$(new_wave_state "$SESSION_WAVEHIST_PRECURSOR" N1)
graph_dispatch_begin_wave "$state_precursor" >/dev/null 2>&1
rc_precursor_begin=$?
wave_id_precursor=$(jq -r '.graph.active_wave.wave_id // empty' "$state_precursor")
precursor_cursor=$(jq -r '.graph.active_wave.transcript_cursor // empty' "$state_precursor")
# N1 completes via a SEPARATE, hand-written, genuinely cursorless wave (no
# transcript_cursor key) — never through wave_id_precursor at all — so its
# evidence is legitimately empty and this is not a case the sibling-anchored
# path could confuse with a real bind either.
jq '.graph.active_wave = {wave_id:("wave-" + (.revision|tostring)),revision:.revision,nodes:["N1"]}' \
	"$state_precursor" >"$state_precursor.tmp" && mv "$state_precursor.tmp" "$state_precursor"
wave_id_cursorless=$(jq -r '.graph.active_wave.wave_id' "$state_precursor")
graph_dispatch_record "$state_precursor" \
	"$(jq -cn --arg w "$wave_id_cursorless" '{wave_id:$w,results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_precursor_record=$?
revision_precursor=$(jq -r '.revision' "$state_precursor")
if [ "$rc_precursor_begin" -ne 0 ] || [ "$rc_precursor_record" -ne 0 ] ||
	[ -z "$wave_id_precursor" ] || [ "$wave_id_precursor" != "wave-2" ] ||
	! jq -e --arg w "$wave_id_precursor" \
		'(.graph.wave_history[$w].nodes | index("N1")) != null
         and .graph.nodes.N1.status == "done" and .graph.nodes.N1.evidence == []' \
		"$state_precursor" >/dev/null 2>&1; then
	fail "a spawn row forward-forged before its claimed wave's own cursor is not wrongly demanded" \
		"setup: begin_wave did not mint wave-2 as expected, or N1 did not complete cursorless (rc_begin=$rc_precursor_begin rc_record=$rc_precursor_record wave_id=$wave_id_precursor)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif [ "$precursor_cursor" -lt 1 ]; then
	fail "a spawn row forward-forged before its claimed wave's own cursor is not wrongly demanded" \
		"setup: the pre-cursor spawn row's line does not actually precede the wave's own cursor (cursor=$precursor_cursor)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
else
	write_valid_triple "$SESSION_WAVEHIST_PRECURSOR" "$LOOP" "$revision_precursor" \
		"$TMP/e_$SESSION_WAVEHIST_PRECURSOR.json" "$TMP/p_$SESSION_WAVEHIST_PRECURSOR.json" \
		"$TMP/r_$SESSION_WAVEHIST_PRECURSOR.json"
	if complete_with "$state_precursor" "$SESSION_WAVEHIST_PRECURSOR" >/dev/null 2>&1; then
		pass "a spawn row forward-forged before its claimed wave's own cursor is not wrongly demanded"
	else
		fail "a spawn row forward-forged before its claimed wave's own cursor is not wrongly demanded" \
			"completion was refused; the pre-cursor row was wrongly counted as dispatched in wave-2"
	fi
fi

# --- ALL evidence deleted from a SECOND done node, while a FIRST done node's
# bound evidence is left intact ------------------------------------------------
# With N1's bound evidence still present, the probe finds it, JQ_MAIN runs —
# and N2 (also done, also genuinely dispatched in the SAME bound wave, but
# with evidence:[]) must still be independently demanded: N1's surviving
# evidence proves wave-1 genuinely bound something, so N2's absence from
# $bound cannot be explained by "wave-1 never bound anyone" the way a
# cursorless wave can. This is the case that pins the demand is made
# per-dispatched-node inside JQ_MAIN, scoped to $bound_waves, not merely at
# the top-level probe.
SESSION_EMPTIED2="tamper-emptiedevidence-twonode"
claude_fixture::init "$PROJECTS" "$SESSION_EMPTIED2"
CURSOR_EMPTIED2=$(claude_fixture::cursor "$PROJECTS" "$SESSION_EMPTIED2")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_EMPTIED2" N1 wave-1 toolu_EMPTIED2N101 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$SESSION_EMPTIED2" N2 wave-1 toolu_EMPTIED2N201 >/dev/null
append_notification "$PROJECTS" "$SESSION_EMPTIED2" toolu_EMPTIED2N101 completed
append_notification "$PROJECTS" "$SESSION_EMPTIED2" toolu_EMPTIED2N201 completed
state_emptied2="$TMP/state_emptied2.json"
jq -n --arg session "$SESSION_EMPTIED2" --arg loop "$LOOP" --argjson c "$CURSOR_EMPTIED2" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state_emptied2"
graph_dispatch_record "$state_emptied2" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]},N2:{outcome:"done",evidence:[]}}}')" \
	>/dev/null 2>&1
rc_emptied2=$?
jq '.graph.active_wave = null | .revision = 2' "$state_emptied2" >"$state_emptied2.tmp" &&
	mv "$state_emptied2.tmp" "$state_emptied2"
write_valid_triple "$SESSION_EMPTIED2" "$LOOP" 2 "$TMP/e_$SESSION_EMPTIED2.json" \
	"$TMP/p_$SESSION_EMPTIED2.json" "$TMP/r_$SESSION_EMPTIED2.json"
if [ "$rc_emptied2" -ne 0 ] ||
	! jq -e '.graph.nodes.N1.evidence[0].kind == "claude_agent"
	         and .graph.nodes.N2.evidence[0].kind == "claude_agent"' \
		"$state_emptied2" >/dev/null 2>&1; then
	fail "a second done node's deleted evidence is refused even when a sibling node's evidence survives" \
		"setup: both nodes did not bind legitimately (rc=$rc_emptied2)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
else
	jq '.graph.nodes.N2.evidence = []' "$state_emptied2" >"$state_emptied2.tmp" &&
		mv "$state_emptied2.tmp" "$state_emptied2"
	if out=$(complete_with "$state_emptied2" "$SESSION_EMPTIED2"); then
		fail "a second done node's deleted evidence is refused even when a sibling node's evidence survives" \
			"completion SUCCEEDED with N2's evidence emptied while N1's evidence and both real spawns survive (bypass)"
	elif ! printf '%s' "$out" | grep -qi -- 'revalidat'; then
		fail "a second done node's deleted evidence is refused even when a sibling node's evidence survives" \
			"refused, but not for a revalidation reason; got: $out"
	else
		pass "a second done node's deleted evidence is refused even when a sibling node's evidence survives"
	fi
fi

# --- negative control: a done node with NO real dispatch in the transcript
# at all must still pass (do not regress the legitimate legacy/no-graph-
# dispatch case) -------------------------------------------------------------
# No Agent tool_use for N1 exists anywhere in this transcript — the node was
# never dispatched via the graph, e.g. loop-scope work done directly. This
# must behave exactly like the existing "legacy" cases above: complete
# without demanding evidence it was never bound against.
SESSION_NEVERDISPATCHED="complete-neverdispatched"
claude_fixture::init "$PROJECTS" "$SESSION_NEVERDISPATCHED"
claude_fixture::append_noise "$PROJECTS" "$SESSION_NEVERDISPATCHED"
state_neverdispatched="$TMP/state_neverdispatched.json"
jq -n --arg session "$SESSION_NEVERDISPATCHED" --arg loop "$LOOP" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:2,status:"in-progress",
   graph:{nodes:{N1:{status:"done",outcome:"done",retry:{attempts:0,max:2},
                     evidence:[]}},
          edges:[],joins:{},active_wave:null,hard_stop:null}}' >"$state_neverdispatched"
write_valid_triple "$SESSION_NEVERDISPATCHED" "$LOOP" 2 "$TMP/e_$SESSION_NEVERDISPATCHED.json" \
	"$TMP/p_$SESSION_NEVERDISPATCHED.json" "$TMP/r_$SESSION_NEVERDISPATCHED.json"
if complete_with "$state_neverdispatched" "$SESSION_NEVERDISPATCHED" >/dev/null 2>&1; then
	pass "a done node never dispatched via the graph still completes (negative control)"
else
	fail "a done node never dispatched via the graph still completes (negative control)" \
		"the empty-evidence fix regressed a legitimately never-bound node"
fi

# --- negative control: a REAL spawn exists, but its wave was CURSORLESS, so
# bind itself left the node legitimately unbound — completion must still
# succeed ----------------------------------------------------------------
# The case review caught: an earlier version of the empty-evidence fix
# demanded evidence for EVERY node any spawn row names, wider than bind's own
# candidate contract (node_id + wave_id + line > cursor). A cursorless wave
# forces bind's own $matches empty (graph_evidence_bind.sh's own comment),
# so a node dispatched inside one has a real Agent spawn in the transcript
# but NO bound evidence — by design, not tamper. Built through the REAL
# graph_dispatch_record path (active_wave carries no transcript_cursor key
# at all, exactly what graph_dispatch_begin_wave omits when no transcript
# resolves at wave-open time), not a hand-written progress.json, so this
# is not a fixture artifact.
SESSION_CURSORLESS="complete-cursorless"
claude_fixture::init "$PROJECTS" "$SESSION_CURSORLESS"
claude_fixture::append_spawn "$PROJECTS" "$SESSION_CURSORLESS" N1 wave-1 toolu_CURSORLESS01 >/dev/null
state_cursorless="$TMP/state_cursorless.json"
jq -n --arg session "$SESSION_CURSORLESS" --arg loop "$LOOP" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
   graph:{nodes:{N1:{status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]}},
          edges:[],joins:{},
          active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"]},
          hard_stop:null}}' >"$state_cursorless"
graph_dispatch_record "$state_cursorless" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_cursorless=$?
jq '.graph.active_wave = null | .revision = 2' "$state_cursorless" >"$state_cursorless.tmp" &&
	mv "$state_cursorless.tmp" "$state_cursorless"
write_valid_triple "$SESSION_CURSORLESS" "$LOOP" 2 "$TMP/e_$SESSION_CURSORLESS.json" \
	"$TMP/p_$SESSION_CURSORLESS.json" "$TMP/r_$SESSION_CURSORLESS.json"
if [ "$rc_cursorless" -ne 0 ] || ! jq -e '.graph.nodes.N1.evidence == []' "$state_cursorless" >/dev/null 2>&1; then
	fail "a cursorless-wave done node with a real but legitimately-unbound spawn still completes" \
		"setup: record did not happen or bound evidence unexpectedly landed on N1 (rc=$rc_cursorless)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif complete_with "$state_cursorless" "$SESSION_CURSORLESS" >/dev/null 2>&1; then
	pass "a cursorless-wave done node with a real but legitimately-unbound spawn still completes"
else
	fail "a cursorless-wave done node with a real but legitimately-unbound spawn still completes" \
		"the empty-evidence fix regressed a legitimately unbound cursorless-wave node"
fi

# --- same cursorless-wave case, but the node ends up SKIPPED instead of
# done, mirroring the reviewer's third reproduced variant --------------------
SESSION_CURSORLESS_SKIP="complete-cursorlessskip"
claude_fixture::init "$PROJECTS" "$SESSION_CURSORLESS_SKIP"
claude_fixture::append_spawn "$PROJECTS" "$SESSION_CURSORLESS_SKIP" N1 wave-1 toolu_CURSORLESSSKIP01 >/dev/null
state_cursorless_skip="$TMP/state_cursorlessskip.json"
jq -n --arg session "$SESSION_CURSORLESS_SKIP" --arg loop "$LOOP" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
   graph:{nodes:{N1:{status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]}},
          edges:[],joins:{},
          active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"]},
          hard_stop:null}}' >"$state_cursorless_skip"
graph_dispatch_record "$state_cursorless_skip" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"failed",evidence:[]}}}')" >/dev/null 2>&1
rc_cursorless_skip=$?
jq '.graph.active_wave = null | .revision = 2
  | .graph.nodes.N1.status = "skipped" | .graph.nodes.N1.outcome = "skipped"' \
	"$state_cursorless_skip" >"$state_cursorless_skip.tmp" && mv "$state_cursorless_skip.tmp" "$state_cursorless_skip"
write_valid_triple "$SESSION_CURSORLESS_SKIP" "$LOOP" 2 "$TMP/e_$SESSION_CURSORLESS_SKIP.json" \
	"$TMP/p_$SESSION_CURSORLESS_SKIP.json" "$TMP/r_$SESSION_CURSORLESS_SKIP.json"
if [ "$rc_cursorless_skip" -ne 0 ] ||
	! jq -e '.graph.nodes.N1.evidence == [] and .graph.nodes.N1.status == "skipped"' \
		"$state_cursorless_skip" >/dev/null 2>&1; then
	fail "a cursorless-wave SKIPPED node with a real but legitimately-unbound spawn still completes" \
		"setup: record did not happen or bound evidence unexpectedly landed on N1 (rc=$rc_cursorless_skip)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif complete_with "$state_cursorless_skip" "$SESSION_CURSORLESS_SKIP" >/dev/null 2>&1; then
	pass "a cursorless-wave SKIPPED node with a real but legitimately-unbound spawn still completes"
else
	fail "a cursorless-wave SKIPPED node with a real but legitimately-unbound spawn still completes" \
		"the empty-evidence fix regressed a legitimately unbound cursorless-wave skipped node"
fi

# --- cross-wave boundary, nothing tampered: a legitimately-bound wave-1 node
# alongside a legitimately cursorless wave-2 node in the SAME graph --------
# $bound_waves is keyed per wave_id, not per graph — reviewed and confirmed:
# a wave with its own surviving bound entry does NOT extend protection to a
# DIFFERENT wave in the same graph (disclosed as a residual in the PR body).
# This fixture pins the un-tampered side of that same boundary: N1's real
# bind in a cursored wave-1 must not somehow cause N2's legitimately-unbound
# cursorless wave-2 dispatch to be wrongly demanded evidence it was never
# bound against. Nothing here is tampered — both nodes' evidence is exactly
# what graph_dispatch_record legitimately wrote.
SESSION_CROSSWAVE="complete-crosswave-boundary"
claude_fixture::init "$PROJECTS" "$SESSION_CROSSWAVE"
CURSOR_CROSSWAVE=$(claude_fixture::cursor "$PROJECTS" "$SESSION_CROSSWAVE")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_CROSSWAVE" N1 wave-1 toolu_CROSSWAVEN101 >/dev/null
append_notification "$PROJECTS" "$SESSION_CROSSWAVE" toolu_CROSSWAVEN101 completed
state_crosswave="$TMP/state_crosswave.json"
jq -n --arg session "$SESSION_CROSSWAVE" --arg loop "$LOOP" --argjson c "$CURSOR_CROSSWAVE" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
   graph:{nodes:{N1:{status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]},
                 N2:{status:"pending",outcome:"pending",retry:{attempts:0,max:2},evidence:[]}},
          edges:[],joins:{},
          active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
          hard_stop:null}}' >"$state_crosswave"
graph_dispatch_record "$state_crosswave" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_crosswave1=$?
# wave-2 is CURSORLESS by construction: no transcript_cursor key at all.
jq '.graph.active_wave = {wave_id:"wave-2",revision:2,nodes:["N2"]}
  | .graph.nodes.N2.status = "running" | .graph.nodes.N2.outcome = "running"
  | .revision = 2' "$state_crosswave" >"$state_crosswave.tmp" && mv "$state_crosswave.tmp" "$state_crosswave"
claude_fixture::append_spawn "$PROJECTS" "$SESSION_CROSSWAVE" N2 wave-2 toolu_CROSSWAVEN201 >/dev/null
graph_dispatch_record "$state_crosswave" \
	"$(jq -cn '{wave_id:"wave-2",results:{N2:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_crosswave2=$?
jq '.graph.active_wave = null | .revision = 3' "$state_crosswave" >"$state_crosswave.tmp" &&
	mv "$state_crosswave.tmp" "$state_crosswave"
write_valid_triple "$SESSION_CROSSWAVE" "$LOOP" 3 "$TMP/e_$SESSION_CROSSWAVE.json" \
	"$TMP/p_$SESSION_CROSSWAVE.json" "$TMP/r_$SESSION_CROSSWAVE.json"
if [ "$rc_crosswave1" -ne 0 ] || [ "$rc_crosswave2" -ne 0 ] ||
	! jq -e '.graph.nodes.N1.evidence[0].kind == "claude_agent" and (.graph.nodes.N2.evidence == [])' \
		"$state_crosswave" >/dev/null 2>&1; then
	fail "a legitimately-bound wave-1 node alongside a legitimately-unbound cursorless wave-2 node still completes" \
		"setup: wave-1 did not bind or wave-2 unexpectedly bound (rc1=$rc_crosswave1 rc2=$rc_crosswave2)"
	SETUP_FAILS=$((SETUP_FAILS + 1))
elif complete_with "$state_crosswave" "$SESSION_CROSSWAVE" >/dev/null 2>&1; then
	pass "a legitimately-bound wave-1 node alongside a legitimately-unbound cursorless wave-2 node still completes"
else
	fail "a legitimately-bound wave-1 node alongside a legitimately-unbound cursorless wave-2 node still completes" \
		"cross-wave scoping wrongly demanded evidence for N2's legitimately-unbound cursorless wave-2 dispatch"
fi

# --- per-attempt sequence: deleting only the FAILED attempt's evidence,
# keeping the successful retry's, must still be refused ---------------------
# The per-node presence/uniqueness/spawn checks above all pass on this shape:
# the node still has ONE valid claude_agent entry with an agent_id, a live
# spawn, and a completed notification — exactly what the terminal-result
# recheck (JQ_MAIN, "Checked PER NODE") demands. What none of those checks
# verify is that the SURVIVING entries are the ATTEMPT SEQUENCE bind actually
# produced (1..retry.attempts+1, contiguous) rather than any one qualifying
# leftover. Deleting the earlier failed attempt's entry and keeping only the
# later successful one satisfies every existing check while erasing the
# node's real retry history — this is the gap graph_evidence.py's
# `sorted(attempts) != range(1, expected_count+1)` check closes for Codex and
# this bash gate does not yet close for Claude.
#
# Built via the REAL dispatch path (graph_dispatch_record), mirroring the
# frozen eval's own tamper_probe.sh fixture and the existing
# "a retried node with a carried-forward attempt entry still completes" case
# above — never a hand-built evidence blob.
SESSION_ATTSEQ="complete-attempt-sequence"
claude_fixture::init "$PROJECTS" "$SESSION_ATTSEQ"
CURSOR_AS1=$(claude_fixture::cursor "$PROJECTS" "$SESSION_ATTSEQ")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_ATTSEQ" N1 wave-1 toolu_ATTSEQ1 >/dev/null
state_attseq="$TMP/state_attseq.json"
jq -n --arg session "$SESSION_ATTSEQ" --arg loop "$LOOP" --argjson c "$CURSOR_AS1" '
  {schema_version:2,session_id:$session,loop_id:$loop,revision:1,status:"in-progress",
   graph:{nodes:{N1:{status:"running",outcome:"running",retry:{attempts:0,max:3},evidence:[]}},
          edges:[],joins:{},
          active_wave:{wave_id:"wave-1",revision:1,nodes:["N1"],transcript_cursor:$c},
          hard_stop:null}}' >"$state_attseq"
# Attempt 1 fails: binds a spawn reference with NO agent_id (no notification).
graph_dispatch_record "$state_attseq" \
	"$(jq -cn '{wave_id:"wave-1",results:{N1:{outcome:"failed",evidence:[]}}}')" >/dev/null 2>&1
rc_attseq1=$?
# Attempt 2 succeeds: binds a second spawn WITH an agent_id.
CURSOR_AS2=$(claude_fixture::cursor "$PROJECTS" "$SESSION_ATTSEQ")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_ATTSEQ" N1 wave-2 toolu_ATTSEQ2 >/dev/null
append_notification "$PROJECTS" "$SESSION_ATTSEQ" toolu_ATTSEQ2 completed
jq --argjson c "$CURSOR_AS2" '.revision = 2
  | .graph.nodes.N1.status = "running" | .graph.nodes.N1.outcome = "running"
  | .graph.active_wave = {wave_id:"wave-2",revision:2,nodes:["N1"],transcript_cursor:$c}' \
	"$state_attseq" >"$state_attseq.tmp" && mv "$state_attseq.tmp" "$state_attseq"
graph_dispatch_record "$state_attseq" \
	"$(jq -cn '{wave_id:"wave-2",results:{N1:{outcome:"done",evidence:[]}}}')" >/dev/null 2>&1
rc_attseq2=$?
jq '.graph.active_wave = null | .revision = 3' "$state_attseq" >"$state_attseq.tmp" && mv "$state_attseq.tmp" "$state_attseq"
write_valid_triple "$SESSION_ATTSEQ" "$LOOP" 3 "$TMP/e_$SESSION_ATTSEQ.json" \
	"$TMP/p_$SESSION_ATTSEQ.json" "$TMP/r_$SESSION_ATTSEQ.json"
attseq_setup_reason="setup: the two-attempt evidence trail was not built (rc1=$rc_attseq1 rc2=$rc_attseq2)"
if [ "$rc_attseq1" -ne 0 ] || [ "$rc_attseq2" -ne 0 ] ||
	! jq -e '[.graph.nodes.N1.evidence[] | select(type=="object") | .attempt] == [1,2]' \
		"$state_attseq" >/dev/null 2>&1; then
	fail "a done node whose attempt-1 evidence is deleted while attempt-2's remains is refused" "$attseq_setup_reason"
	fail "a done node with an intact contiguous 2-attempt evidence trail still completes" "$attseq_setup_reason"
	SETUP_FAILS=$((SETUP_FAILS + 2))
else
	# Positive control on a COPY, before any tampering: proves the refusal
	# below reacts to the deletion, not this fixture shape outright.
	state_attseq_intact="$TMP/state_attseq_intact.json"
	cp "$state_attseq" "$state_attseq_intact"
	if complete_with "$state_attseq_intact" "$SESSION_ATTSEQ" >/dev/null 2>&1; then
		pass "a done node with an intact contiguous 2-attempt evidence trail still completes"
	else
		fail "a done node with an intact contiguous 2-attempt evidence trail still completes" \
			"completion was refused on untampered, contiguous [1,2] evidence"
	fi
	# The attack: delete ONLY the attempt-1 evidence object, keeping
	# attempt-2's; no other field (retry.attempts included) touched.
	jq '.graph.nodes.N1.evidence |= [.[] | select(type != "object" or .attempt != 1)]' \
		"$state_attseq" >"$state_attseq.tmp" && mv "$state_attseq.tmp" "$state_attseq"
	assert_refused_revalidation \
		"a done node whose attempt-1 evidence is deleted while attempt-2's remains is refused" \
		"$state_attseq" "$SESSION_ATTSEQ"
fi

[ "$SETUP_FAILS" -gt 0 ] && printf 'NOTE: %d case(s) failed in SETUP — those measure the fixture, not the gate.\n' "$SETUP_FAILS"

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS\n'
	exit 0
else
	printf 'FAIL (%d)\n' "$FAILS"
	exit 1
fi
