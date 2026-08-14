#!/bin/bash
# Smoke test for graph_executor.sh's collect-before-write mechanism (D1):
# a wave containing 2 nodes' worth of results must land via EXACTLY ONE
# als_atomic_progress_update call, never one call per node. Call count is
# proven by wrapping als_atomic_progress_update itself (the actual locked
# read-modify-write primitive) with a counting shim, not by inference.
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
ok() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n      %s\n' "$1" "$2"; fails=$((fails+1)); }

# --- fixture progress.json: two pending nodes A, B, no edges/joins ---
jq -n '
  {
    graph: {
      nodes: {
        A: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}},
        B: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
      },
      edges: [],
      joins: {}
    },
    decisions_absorbed: []
  }
' > "$TMP/progress.json"

# --- source graph_executor.sh, then wrap als_atomic_progress_update to count calls ---
. "$LIB_DIR/graph_executor.sh"

CALL_LOG="$TMP/calls.log"
: > "$CALL_LOG"
eval "$(declare -f als_atomic_progress_update | sed '1s/als_atomic_progress_update/__real_als_atomic_progress_update/')"
als_atomic_progress_update() {
  echo "call" >> "$CALL_LOG"
  __real_als_atomic_progress_update "$@"
}

WAVE_JSON='{
  "A": {"status":"done", "outcome":"done"},
  "B": {"status":"done", "outcome":"done"},
  "decisions_absorbed": [{"phase":"test","decision":"wave applied"}]
}'

graph_executor_apply_wave "$TMP/progress.json" "$WAVE_JSON"
rc=$?

call_count=$(wc -l < "$CALL_LOG" | tr -d ' ')

[ "$rc" -eq 0 ] && ok "graph_executor_apply_wave returns 0" || fail "graph_executor_apply_wave returns 0" "rc=$rc"
[ "$call_count" = "1" ] && ok "exactly ONE als_atomic_progress_update call for a 2-node wave" \
  || fail "exactly ONE als_atomic_progress_update call for a 2-node wave" "call_count=$call_count"

a_outcome=$(jq -r '.graph.nodes.A.outcome' "$TMP/progress.json")
b_outcome=$(jq -r '.graph.nodes.B.outcome' "$TMP/progress.json")
a_retry_max=$(jq -r '.graph.nodes.A.retry.max' "$TMP/progress.json")
decisions_len=$(jq '.decisions_absorbed | length' "$TMP/progress.json")

[ "$a_outcome" = "done" ] && ok "node A outcome landed as done" || fail "node A outcome landed as done" "got=$a_outcome"
[ "$b_outcome" = "done" ] && ok "node B outcome landed as done" || fail "node B outcome landed as done" "got=$b_outcome"
[ "$a_retry_max" = "5" ] && ok "node A's pre-existing retry.max survived the merge (not clobbered)" \
  || fail "node A's pre-existing retry.max survived the merge" "got=$a_retry_max"
[ "$decisions_len" = "1" ] && ok "decisions_absorbed entry appended" || fail "decisions_absorbed entry appended" "len=$decisions_len"

# --- readiness enumeration: no edges, so both A and B are vacuously ready before the wave ---
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}},
                       B:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} } }
' > "$TMP/ready_fixture.json"
ready=$(graph_executor_ready_nodes "$TMP/ready_fixture.json" | sort | tr '\n' ',' )
[ "$ready" = "A,B," ] && ok "graph_executor_ready_nodes enumerates both vacuously-ready nodes" \
  || fail "graph_executor_ready_nodes enumerates both vacuously-ready nodes" "got=$ready"

# --- exit-status contract: last-enumerated node BLOCKED must not flip the function's own rc ---
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}},
                       Z:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [{from:"A",to:"Z"}], joins: {} } }
' > "$TMP/ready_blocked_last.json"
ready2=$(graph_executor_ready_nodes "$TMP/ready_blocked_last.json"); rc_ready=$?
[ "$rc_ready" -eq 0 ] && [ "$ready2" = "A" ] && ok "ready_nodes exit 0 even when last-enumerated node (Z) is blocked" \
  || fail "ready_nodes exit 0 even when last-enumerated node (Z) is blocked" "rc=$rc_ready out=$ready2"

# --- fail-closed: non-object wave-results never attempts a write ---
: > "$CALL_LOG"
graph_executor_apply_wave "$TMP/progress.json" '[]'
rc2=$?
call_count2=$(wc -l < "$CALL_LOG" | tr -d ' ')
[ "$rc2" -ne 0 ] && [ "$call_count2" = "0" ] && ok "non-object wave-results fails closed, no write attempted" \
  || fail "non-object wave-results fails closed, no write attempted" "rc=$rc2 call_count=$call_count2"

# --- fail-closed: an id not already in .graph.nodes must never be created ---
: > "$CALL_LOG"
graph_executor_apply_wave "$TMP/progress.json" '{"NOPE": {"status":"done","outcome":"done"}}'
rc3=$?
call_count3=$(wc -l < "$CALL_LOG" | tr -d ' ')
nope_exists=$(jq 'has("NOPE") | not' <(jq '.graph.nodes' "$TMP/progress.json"))
[ "$rc3" -ne 0 ] && [ "$call_count3" = "0" ] && [ "$nope_exists" = "true" ] \
  && ok "unknown node id fails closed, never created" \
  || fail "unknown node id fails closed, never created" "rc=$rc3 call_count=$call_count3 not_created=$nope_exists"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
