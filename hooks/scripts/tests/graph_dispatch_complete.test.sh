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
SESSION_SKIP="complete-skipnode"
claude_fixture::init "$PROJECTS" "$SESSION_SKIP"
CURSOR_SKIP=$(claude_fixture::cursor "$PROJECTS" "$SESSION_SKIP")
claude_fixture::append_spawn "$PROJECTS" "$SESSION_SKIP" N1 wave-1 toolu_SKIPDONE01 >/dev/null
claude_fixture::append_spawn "$PROJECTS" "$SESSION_SKIP" N2 wave-1 toolu_SKIPCARRY01 >/dev/null
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
		"the spawn demand deadlocked a legitimately skipped node"
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

[ "$SETUP_FAILS" -gt 0 ] && printf 'NOTE: %d case(s) failed in SETUP — those measure the fixture, not the gate.\n' "$SETUP_FAILS"

if [[ "$FAILS" -eq 0 ]]; then
	printf 'PASS\n'
	exit 0
else
	printf 'FAIL (%d)\n' "$FAILS"
	exit 1
fi
