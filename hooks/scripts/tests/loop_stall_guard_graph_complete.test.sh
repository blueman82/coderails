#!/bin/bash
# Behavioural test for gate_graph_complete's proof.json check
# (hooks/scripts/loop_stall_guard.sh). Kept as a separate file from
# loop_stall_guard.test.sh so this gate's cases don't need to touch every
# existing case in that (already very large) file — run_all.sh globs both.
#
# The bug this fixes: gate_graph_complete unconditionally required
# proof.json to exist and be well-formed for any graph-based loop, refusing
# `complete` with "proof.json belongs to another loop" even when proof.json
# was legitimately absent — either grandfathered by progress.json's
# schema_version < 2, or excused by a valid proof_disposition ("none" /
# "none: <reason>"). als_gate_proofs_on_complete (loop_state_common.sh)
# already fully adjudicates that absence and runs unconditionally, just
# before gate_graph_complete, in gate_loop_stop_declared. The fix drops the
# duplicated presence/shape check and only validates proof.json's identity
# (session_id/loop_id) when the file is actually present — the one thing
# the sibling gate never checks.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/loop_stall_guard.sh"
POST_EVALS="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/post_evals.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
CWD="/work/project"
SLUG="-work-project"
fails=0
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }   # session_id -> dir

mk_transcript() { # final_text -> path (one agentic-loop invocation, then the final assistant text)
  local final="$1" out="$TMP/t_${RANDOM}.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$out"
  jq -cn --arg t "$final" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$out"
  printf '%s' "$out"
}
payload() { # transcript session_id
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":false}' "$1" "$2" "$CWD"
}
run() { echo "$2" | bash "$GUARD" >/dev/null 2>&1; echo $?; }
run_capture_stderr() { # payload -> sets $RC_OUT and $STDERR_OUT (no subshell)
  local errfile="$TMP/stderr_${RANDOM}.txt"
  echo "$1" | bash "$GUARD" >/dev/null 2>"$errfile"
  RC_OUT=$?
  STDERR_OUT=$(cat "$errfile" 2>/dev/null)
  rm -f "$errfile"
}

# stamp <evals_json_path>: grades a fixture in place using the REAL
# post_evals::grade_loop, so "properly stamped" test fixtures are byte-
# identical to what the writer produces — never hand-computed here (same
# pattern as loop_state_guard_evals.test.sh).
# shellcheck disable=SC1090
stamp() { ( source "$POST_EVALS" >/dev/null 2>&1; post_evals::grade_loop "$1" >/dev/null ) || { printf 'stamp: grade_loop refused %s\n' "$1" >&2; return 1; } }

# Shared fixture builder: a completed graph + all-done work_units + a real
# GO-stamped evals.json (verification_level:0, empty evals — grade_loop's
# vacuous-true GO path), so the outcome at the point of the proof.json check
# is genuinely decided by that check alone, not by an earlier gate in the
# chain (evals/work_units/graph-unfinished).
mk_graph_complete_fixture() { # session loop_id -> writes progress.json + evals.json into file_dir(session)
  local session="$1" loop="$2" d
  d=$(file_dir "$session"); mkdir -p "$d"
  jq -n --arg s "$session" --arg l "$loop" \
    '{schema_version:1, status:"in-progress", session_id:$s, completed_marker:0,
      loop_id:$l, revision:1,
      work_units:{U1:{status:"done"}},
      graph:{nodes:{A:{status:"done"}}, edges:[], joins:{}, active_wave:null, hard_stop:null}}' \
    >"$d/progress.json"
  jq -n --arg s "$session" --arg l "$loop" \
    '{schema_version:1, scope:"loop", session_id:$s, loop_id:$l, revision:1,
      verification_level:0, verification_justification:"no executable surface",
      frozen_at:"2026-08-24T00:00:00Z", frozen_sha:"aaaabbbbcccc", head_sha:"deadbeef",
      amendments:[], result:null, grading:null, evals:[]}' \
    >"$d/evals.json"
  stamp "$d/evals.json"
}
# retro.json with session_id/loop_id matching the fixture, so
# gate_graph_complete's OWN (separate, unfixed — out of scope for this
# task's brief, which names only proof.json) retro.json identity check
# doesn't block before reaching the proof.json check these cases exist to
# exercise.
write_matching_retro() { # session loop_id -> writes matching retro.json
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  jq -n --arg s "$1" --arg l "$2" '{schema_version:1, session_id:$s, loop_id:$l}' > "$dir/retro.json"
}

# (1) HAPPY PATH — absent proof.json, schema_version 1 (grandfathered) ->
# ALLOW. This is the exact case the bug blocked: graph-based loop, no
# proof.json, and the sibling gate's own grandfather clause should carry it
# straight through.
reset; mk_graph_complete_fixture S1 loop-graph1
write_matching_retro S1 loop-graph1
t1=$(mk_transcript "LOOP-STOP: complete — no executable surface")
check "absent proof.json, grandfathered schema_version -> allow" 0 "$(run x "$(payload "$t1" S1)")"

# (2) HAPPY PATH — absent proof.json, schema_version 2 with a VALID
# proof_disposition ("none: <reason>") -> ALLOW. Proves the disposition
# escape hatch itself (not just grandfathering) is reachable for a
# graph-based loop.
reset; d=$(file_dir S1); mkdir -p "$d"
mk_graph_complete_fixture S1 loop-graph2
jq '.schema_version = 2 | .proof_disposition = "none: no executable surface"' "$d/progress.json" > "$d/progress.json.tmp" && mv "$d/progress.json.tmp" "$d/progress.json"
write_matching_retro S1 loop-graph2
t2=$(mk_transcript "LOOP-STOP: complete — no executable surface")
check "absent proof.json, schema_version 2 + valid proof_disposition -> allow" 0 "$(run x "$(payload "$t2" S1)")"

# (3) NEGATIVE CONTROL — absent proof.json, schema_version 2, NO
# proof_disposition -> still BLOCKS, and via the SIBLING gate's wording
# (als_gate_proofs_on_complete), not gate_graph_complete's own "belongs to
# another loop" message — proving the block comes from the disposition
# check being genuinely enforced, not merely from any block existing (an
# exit-code-only assertion would stay green even if this whole fix were
# reverted, since the unconditional pre-fix check also blocks this case).
reset; d=$(file_dir S1); mkdir -p "$d"
mk_graph_complete_fixture S1 loop-graph3
jq '.schema_version = 2' "$d/progress.json" > "$d/progress.json.tmp" && mv "$d/progress.json.tmp" "$d/progress.json"
write_matching_retro S1 loop-graph3
t3=$(mk_transcript "LOOP-STOP: complete — no executable surface")
run_capture_stderr "$(payload "$t3" S1)"
check "absent proof.json, schema_version 2, no disposition -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"no proof_disposition"*) sibling_msg=1 ;; *) sibling_msg=0 ;; esac
check "no-disposition block comes from the sibling proof gate's wording" 1 "$sibling_msg"
case "$STDERR_OUT" in *"belongs to another loop"*) graph_msg=1 ;; *) graph_msg=0 ;; esac
check "no-disposition block does NOT use gate_graph_complete's own message" 0 "$graph_msg"

# (4) IDENTITY REGRESSION GUARD — proof.json PRESENT but with EMPTY .proofs
# and .withdrawn_proofs (the sibling's own "nothing to prove" allow, so the
# sibling never mines the transcript and never blocks on its own), yet
# session_id/loop_id inside proof.json do NOT match the current loop ->
# gate_graph_complete's identity check must still catch it and block, using
# its own "belongs to another loop" wording. This is the case the fix must
# not regress: dropping the presence requirement must not also drop the
# identity check on a file that IS present.
reset; d=$(file_dir S1); mkdir -p "$d"
mk_graph_complete_fixture S1 loop-graph4
write_matching_retro S1 loop-graph4
jq -n '{schema_version:1, session_id:"OTHER-SESSION", loop_id:"other-loop", proofs:[], withdrawn_proofs:[]}' > "$d/proof.json"
t4=$(mk_transcript "LOOP-STOP: complete — no executable surface")
run_capture_stderr "$(payload "$t4" S1)"
check "present but wrong-session proof.json -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"belongs to another loop"*) graph_msg4=1 ;; *) graph_msg4=0 ;; esac
check "wrong-session proof.json -> blocked by gate_graph_complete's own identity check" 1 "$graph_msg4"

# (5) REGRESSION — proof.json PRESENT and matching session/loop, empty
# .proofs/.withdrawn_proofs -> ALLOW (the identity check must not itself
# over-block a legitimately empty, correctly-owned proof.json).
reset; d=$(file_dir S1); mkdir -p "$d"
mk_graph_complete_fixture S1 loop-graph5
write_matching_retro S1 loop-graph5
jq -n '{schema_version:1, session_id:"S1", loop_id:"loop-graph5", proofs:[], withdrawn_proofs:[]}' > "$d/proof.json"
t5=$(mk_transcript "LOOP-STOP: complete — no executable surface")
check "present, matching-identity, empty proof.json -> allow" 0 "$(run x "$(payload "$t5" S1)")"

if [ "$fails" -eq 0 ]; then echo "PASS"; exit 0; else echo "FAILED ($fails)"; exit 1; fi
