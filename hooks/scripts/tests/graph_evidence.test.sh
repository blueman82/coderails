#!/usr/bin/env bash
# Provenance binding for Claude graph evidence: a node's evidence must be
# bound to a REAL Agent tool_use in this session's own transcript, and a
# claim that does not match one is refused rather than folded in.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_PROJECTS_DIR="$TMP/projects"
PROJECTS="$CLAUDE_PROJECTS_DIR"
SESSION="session-fixture-0001"

# shellcheck source=hooks/scripts/tests/lib/claude_transcript_fixture.sh
source "$ROOT/hooks/scripts/tests/lib/claude_transcript_fixture.sh"
# shellcheck source=hooks/scripts/lib/graph_dispatch.sh
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

# Report the WHOLE wave (apply_wave requires the reported set to equal
# active_wave.nodes exactly), citing $cite as spawn_ref for $node.
record() { # state node cite
	local state="$1" node="$2" cite="$3" results
	results=$(jq -cn --arg node "$node" --arg cite "$cite" '
      {N1:{outcome:"done",evidence:[]},N2:{outcome:"done",evidence:[]}}
      | .[$node] = {outcome:"done",evidence:[{spawn_ref:$cite}]}')
	graph_dispatch_record "$state" \
		"$(jq -cn --argjson r "$results" '{wave_id:"wave-1",results:$r}')"
}

# ---------------------------------------------------------------------------
# Fixture transcript: one pre-cursor spawn, then the wave's two genuine spawns.
# ---------------------------------------------------------------------------
claude_fixture::init "$PROJECTS" "$SESSION"
PRE=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION" N1 wave-0 toolu_PRECURSOR01)
claude_fixture::append_noise "$PROJECTS" "$SESSION"
CURSOR=$(claude_fixture::cursor "$PROJECTS" "$SESSION")
GEN1=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION" N1 wave-1 toolu_GENUINE0001)
GEN2=$(claude_fixture::append_spawn "$PROJECTS" "$SESSION" N2 wave-1 toolu_OTHERNODE02)

# --- POSITIVE: a genuine, in-wave, own-node spawn is accepted and bound -----
state="$TMP/positive.json"
write_state "$state" "$CURSOR"
if record "$state" N1 "$GEN1" >/dev/null 2>&1; then
	pass "genuine own-node spawn after the cursor is accepted"
	expect_eq "accepted evidence is bound to the real tool_use id" 'true' \
		"$(jq -r --arg id "$GEN1" '[.graph.nodes.N1.evidence[]
            | select(type=="object" and .kind=="claude_agent")]
           | length == 1 and .[0].tool_use_id == $id
             and .[0].wave_id == "wave-1" and .[0].attempt == 1
             and (.[0].record_uuid | type == "string" and length > 0)' "$state")"
	expect_eq "an uncited sibling node still binds from the transcript" 'true' \
		"$(jq -r --arg id "$GEN2" '[.graph.nodes.N2.evidence[]
            | select(type=="object" and .kind=="claude_agent")]
           | length == 1 and .[0].tool_use_id == $id' "$state")"
else
	fail "genuine own-node spawn after the cursor is accepted" "record refused a genuine claim"
fi

# --- NEGATIVE: the cursor itself, isolated ----------------------------------
# The pre-cursor case above uses wave-0, so the wave_id mismatch alone rejects
# it and the cursor never participates — deleting the `.line > $cursor` filter
# leaves it green. This case is the only shape that isolates the lower bound:
# SAME node, SAME wave_id as the wave under test, but recorded BEFORE the
# cursor. Only the cursor can reject it.
STALE_SESSION="session-fixture-stale"
claude_fixture::init "$PROJECTS" "$STALE_SESSION"
STALE=$(claude_fixture::append_spawn "$PROJECTS" "$STALE_SESSION" N1 wave-1 toolu_STALEWAVE01)
STALE_CURSOR=$(claude_fixture::cursor "$PROJECTS" "$STALE_SESSION")
claude_fixture::append_spawn "$PROJECTS" "$STALE_SESSION" N2 wave-1 toolu_STALESIB002 >/dev/null

state="$TMP/cursor_isolated.json"
jq -n --arg session "$STALE_SESSION" --argjson c "$STALE_CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n,N2:$n},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
expect_denied "a same-wave spawn recorded before the cursor is refused" \
	"cites an unbindable spawn" "$state" \
	"$(jq -cn --arg id "$STALE" '{wave_id:"wave-1",results:{
        N1:{outcome:"done",evidence:[{spawn_ref:$id}]},
        N2:{outcome:"done",evidence:[]}}}')"

# --- NEGATIVE: corrupt transcript with NOTHING cited ------------------------
# The dangerous degradation: if a malformed transcript fell back to an empty
# spawn list instead of denying, every node citing nothing would pass through
# silently unbound — a whole wave recorded with zero provenance, and no other
# test would notice. This is what pins the fail-closed line itself.
state="$TMP/corrupt_uncited.json"
write_state "$state" "$CURSOR"
cp "$state" "$TMP/corrupt.before"
mkdir -p "$TMP/corrupt/fixture-project"
printf '{"type":"assistant"\ngarbage not json\n' >"$TMP/corrupt/fixture-project/$SESSION.jsonl"
uncited=$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:[]},N2:{outcome:"done",evidence:[]}}}')
if CLAUDE_PROJECTS_DIR="$TMP/corrupt" graph_dispatch_record "$state" "$uncited" >/dev/null 2>&1; then
	fail "a corrupt transcript refuses even an uncited wave" \
		"whole wave recorded with zero provenance from an unreadable transcript"
else
	pass "a corrupt transcript refuses even an uncited wave"
	expect_eq "the refused corrupt-transcript wave left state untouched" 'same' \
		"$(cmp -s "$TMP/corrupt.before" "$state" && echo same || echo changed)"
fi

# --- NEGATIVE: forgery — id appears nowhere in the transcript ---------------
state="$TMP/forged.json"
write_state "$state" "$CURSOR"
cp "$state" "$TMP/forged.before"
if record "$state" N1 toolu_FORGED9999 >/dev/null 2>&1; then
	fail "forged spawn id is refused" "record accepted an id absent from the transcript"
else
	pass "forged spawn id is refused"
	expect_eq "refused forgery leaves durable state untouched" 'same' \
		"$(cmp -s "$TMP/forged.before" "$state" && echo same || echo changed)"
fi

# --- NEGATIVE: cross-node replay — real id, wrong node ----------------------
state="$TMP/crossnode.json"
write_state "$state" "$CURSOR"
if record "$state" N1 "$GEN2" >/dev/null 2>&1; then
	fail "cross-node replay is refused" "record accepted N2's real spawn id cited for N1"
else
	pass "cross-node replay is refused"
fi

# --- NEGATIVE: pre-cursor replay — real id, but before the wave began -------
state="$TMP/precursor.json"
write_state "$state" "$CURSOR"
if record "$state" N1 "$PRE" >/dev/null 2>&1; then
	fail "pre-cursor replay is refused" "record accepted a spawn preceding the wave cursor"
else
	pass "pre-cursor replay is refused"
fi

# --- NEGATIVE: reuse — an id already bound to a node's earlier attempt ------
state="$TMP/reuse.json"
write_state "$state" "$CURSOR"
jq --arg id "$GEN1" '.graph.nodes.N2.evidence =
     [{kind:"claude_agent",attempt:1,wave_id:"wave-0",tool_use_id:$id,
       record_uuid:"uuid-prior",subagent_type:"coderails:loop-worker"}]' \
	"$state" >"$state.tmp" && mv "$state.tmp" "$state"
if record "$state" N1 "$GEN1" >/dev/null 2>&1; then
	fail "reuse of an already-bound spawn id is refused" "record bound one id twice"
else
	pass "reuse of an already-bound spawn id is refused"
fi

# --- NEGATIVE: a caller writing the BOUND shape directly --------------------
# The gate must be the only minter of provenance references. A caller that
# skips {spawn_ref} and writes a ready-made {kind:"claude_agent",...} object
# would otherwise bypass the check entirely by supplying the OUTPUT shape.
state="$TMP/smuggled.json"
write_state "$state" "$CURSOR"
smuggled=$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:[{kind:"claude_agent",attempt:1,wave_id:"wave-1",
        tool_use_id:"toolu_TOTALLYFAKE",record_uuid:"fake",subagent_type:"x"}]},
    N2:{outcome:"done",evidence:[]}}}')
if graph_dispatch_record "$state" "$smuggled" >/dev/null 2>&1; then
	fail "a caller-supplied bound-shape reference is refused" "forged provenance object was folded in"
else
	pass "a caller-supplied bound-shape reference is refused"
fi

# Same smuggling, but citing a REAL id owned by the sibling node: must not
# bind N2's spawn onto N1 (and must not leave it on both).
state="$TMP/smuggled_real.json"
write_state "$state" "$CURSOR"
smuggled_real=$(jq -cn --arg id "$GEN2" '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:[{kind:"claude_agent",attempt:1,wave_id:"wave-1",
        tool_use_id:$id,record_uuid:"uuid-x",subagent_type:"x"}]},
    N2:{outcome:"done",evidence:[]}}}')
if graph_dispatch_record "$state" "$smuggled_real" >/dev/null 2>&1; then
	fail "a smuggled real sibling id is refused" "one spawn was bound to two nodes"
else
	pass "a smuggled real sibling id is refused"
fi

# --- NEGATIVE: missing transcript ------------------------------------------
state="$TMP/notranscript.json"
write_state "$state" "$CURSOR"
if CLAUDE_PROJECTS_DIR="$TMP/empty" record "$state" N1 "$GEN1" >/dev/null 2>&1; then
	fail "a cited ref with no resolvable transcript is refused" "record passed with no transcript"
else
	pass "a cited ref with no resolvable transcript is refused"
fi

# --- NEGATIVE: malformed transcript ----------------------------------------
state="$TMP/malformed.json"
write_state "$state" "$CURSOR"
mkdir -p "$TMP/bad/fixture-project"
printf 'not json at all\n{"type":"assistant"\n' >"$TMP/bad/fixture-project/$SESSION.jsonl"
if CLAUDE_PROJECTS_DIR="$TMP/bad" record "$state" N1 "$GEN1" >/dev/null 2>&1; then
	fail "a malformed transcript is refused" "record passed on unparseable records"
else
	pass "a malformed transcript is refused"
fi

# --- A retry carries its earlier attempt's ref through, and binds a new one -
# graph_dispatch_record prepends existing node evidence to the wave results, so
# attempt 2 sees attempt 1's minted ref arrive alongside the caller's. It must
# be carried through, not re-validated against the new wave (its spawn is
# necessarily older than the current cursor).
state="$TMP/retry.json"
jq -n --arg session "$SESSION" --argjson c "$CURSOR" '
  {status:"running",outcome:"running",retry:{attempts:1,max:2},
   evidence:["attempt one failed",
             {kind:"claude_agent",attempt:1,wave_id:"wave-0",
              tool_use_id:"toolu_PRIORATTEMPT",record_uuid:"uuid-prior",
              subagent_type:"coderails:loop-worker"}]} as $n1
  | {status:"running",outcome:"running",retry:{attempts:0,max:2},evidence:[]} as $n2
  | {schema_version:2,session_id:$session,loop_id:"loop-fixture",revision:1,
     status:"in-progress",
     graph:{nodes:{N1:$n1,N2:$n2},edges:[],joins:{},
            active_wave:{wave_id:"wave-1",revision:1,nodes:["N1","N2"],transcript_cursor:$c},
            hard_stop:null}}' >"$state"
retry_env=$(jq -cn '{wave_id:"wave-1",results:{
    N1:{outcome:"done",evidence:["attempt two proof"]},
    N2:{outcome:"done",evidence:[]}}}')
if graph_dispatch_record "$state" "$retry_env" >/dev/null 2>&1; then
	expect_eq "a retry keeps the prior ref and binds this attempt to a new spawn" 'true' \
		"$(jq -r --arg new "$GEN1" '[.graph.nodes.N1.evidence[]
            | select(type=="object" and .kind=="claude_agent")] as $refs
           | ($refs | length) == 2
             and ([$refs[].tool_use_id] | unique | length) == 2
             and ($refs[0].tool_use_id == "toolu_PRIORATTEMPT")
             and ($refs[1].tool_use_id == $new)
             and ($refs[1].attempt == 2)' "$state")"
else
	fail "a retry keeps the prior ref and binds this attempt to a new spawn" "record refused a legitimate retry"
fi

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
if CLAUDE_PROJECTS_DIR="$TMP/empty" graph_dispatch_record "$state" "$legacy" >/dev/null 2>&1; then
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
