#!/bin/bash
# Smoke test for graph_executor.sh's collect-before-write mechanism (D1):
# a wave containing 2 nodes' worth of results must land via EXACTLY ONE
# als_atomic_progress_update call, never one call per node. Call count is
# proven by wrapping als_atomic_progress_update itself (the actual locked
# read-modify-write primitive) with a counting shim, not by inference.
# shellcheck disable=SC1091,SC2015 # Computed library source and assertion chains are intentional.
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
ok() { printf 'ok   - %s\n' "$1"; }
fail() {
    printf 'FAIL - %s\n      %s\n' "$1" "$2"
    fails=$((fails + 1))
}

stamp_identity() {
    local path="$1"
    jq '. + {schema_version:2,status:"in-progress",session_id:"session-test",loop_id:"loop-test",revision:1}
        | .graph.nodes |= with_entries(if (.value | type) == "object" and (.value | has("evidence") | not)
            then .value.evidence = [] else . end)' "$path" >"$path.tmp" && mv "$path.tmp" "$path"
}

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
' >"$TMP/progress.json"
stamp_identity "$TMP/progress.json"

# --- source graph_executor.sh, then wrap als_atomic_progress_update to count calls ---
. "$LIB_DIR/graph_executor.sh"

CALL_LOG="$TMP/calls.log"
: >"$CALL_LOG"
eval "$(declare -f als_atomic_progress_update | sed '1s/als_atomic_progress_update/__real_als_atomic_progress_update/')"
als_atomic_progress_update() {
    echo "call" >>"$CALL_LOG"
    __real_als_atomic_progress_update "$@"
}

WAVE_JSON='{
  "A": {"status":"done", "outcome":"done"},
  "B": {"status":"done", "outcome":"done"},
  "decisions_absorbed": [{"phase":"test","decision":"wave applied"}]
}'

graph_executor_apply_wave "$TMP/progress.json" "$WAVE_JSON"
rc=$?

call_count=$(wc -l <"$CALL_LOG" | tr -d ' ')

[ "$rc" -eq 0 ] && ok "graph_executor_apply_wave returns 0" || fail "graph_executor_apply_wave returns 0" "rc=$rc"
[ "$call_count" = "1" ] && ok "exactly ONE als_atomic_progress_update call for a 2-node wave" ||
    fail "exactly ONE als_atomic_progress_update call for a 2-node wave" "call_count=$call_count"

a_outcome=$(jq -r '.graph.nodes.A.outcome' "$TMP/progress.json")
b_outcome=$(jq -r '.graph.nodes.B.outcome' "$TMP/progress.json")
a_retry_max=$(jq -r '.graph.nodes.A.retry.max' "$TMP/progress.json")
decisions_len=$(jq '.decisions_absorbed | length' "$TMP/progress.json")

[ "$a_outcome" = "done" ] && ok "node A outcome landed as done" || fail "node A outcome landed as done" "got=$a_outcome"
[ "$b_outcome" = "done" ] && ok "node B outcome landed as done" || fail "node B outcome landed as done" "got=$b_outcome"
[ "$a_retry_max" = "5" ] && ok "node A's pre-existing retry.max survived the merge (not clobbered)" ||
    fail "node A's pre-existing retry.max survived the merge" "got=$a_retry_max"
[ "$decisions_len" = "1" ] && ok "decisions_absorbed entry appended" || fail "decisions_absorbed entry appended" "len=$decisions_len"

# --- readiness enumeration: no edges, so both A and B are vacuously ready before the wave ---
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}},
                       B:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} } }
' >"$TMP/ready_fixture.json"
stamp_identity "$TMP/ready_fixture.json"
ready=$(graph_executor_ready_nodes "$TMP/ready_fixture.json" | sort | tr '\n' ',')
[ "$ready" = "A,B," ] && ok "graph_executor_ready_nodes enumerates both vacuously-ready nodes" ||
    fail "graph_executor_ready_nodes enumerates both vacuously-ready nodes" "got=$ready"

# --- exit-status contract: last-enumerated node BLOCKED must not flip the function's own rc ---
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}},
                       Z:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [{from:"A",to:"Z"}], joins: {} } }
' >"$TMP/ready_blocked_last.json"
stamp_identity "$TMP/ready_blocked_last.json"
ready2=$(graph_executor_ready_nodes "$TMP/ready_blocked_last.json")
rc_ready=$?
[ "$rc_ready" -eq 0 ] && [ "$ready2" = "A" ] && ok "ready_nodes exit 0 even when last-enumerated node (Z) is blocked" ||
    fail "ready_nodes exit 0 even when last-enumerated node (Z) is blocked" "rc=$rc_ready out=$ready2"

# --- fail-closed: non-object wave-results never attempts a write ---
: >"$CALL_LOG"
graph_executor_apply_wave "$TMP/progress.json" '[]'
rc2=$?
call_count2=$(wc -l <"$CALL_LOG" | tr -d ' ')
[ "$rc2" -ne 0 ] && [ "$call_count2" = "0" ] && ok "non-object wave-results fails closed, no write attempted" ||
    fail "non-object wave-results fails closed, no write attempted" "rc=$rc2 call_count=$call_count2"

# --- fail-closed: an id not already in .graph.nodes must never be created.
# The check runs INSIDE the locked jq filter, closing the TOCTOU race a
# pre-lock read would have, so als_atomic_progress_update IS still called
# (call_count=1) — but its own jq errors, so no write lands.
: >"$CALL_LOG"
graph_executor_apply_wave "$TMP/progress.json" '{"NOPE": {"status":"done","outcome":"done"}}'
rc3=$?
call_count3=$(wc -l <"$CALL_LOG" | tr -d ' ')
nope_exists=$(jq 'has("NOPE") | not' <(jq '.graph.nodes' "$TMP/progress.json"))
[ "$rc3" -ne 0 ] && [ "$call_count3" = "1" ] && [ "$nope_exists" = "true" ] &&
    ok "unknown node id fails closed, never created" ||
    fail "unknown node id fails closed, never created" "rc=$rc3 call_count=$call_count3 not_created=$nope_exists"

# --- fail-closed: invalid status/outcome enum value never lands ---
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/enum_fixture.json"
stamp_identity "$TMP/enum_fixture.json"
graph_executor_apply_wave "$TMP/enum_fixture.json" '{"A":{"status":"merged","outcome":"done"}}'
rc4=$?
a_status_after=$(jq -r '.graph.nodes.A.status' "$TMP/enum_fixture.json")
[ "$rc4" -ne 0 ] && [ "$a_status_after" = "pending" ] &&
    ok "invalid status enum value (e.g. retired 'merged') fails closed, node unchanged" ||
    fail "invalid status enum value fails closed" "rc=$rc4 status_after=$a_status_after"

# --- fail-closed: retry.attempts > retry.max never lands ---
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/retry_fixture.json"
stamp_identity "$TMP/retry_fixture.json"
graph_executor_apply_wave "$TMP/retry_fixture.json" '{"A":{"status":"done","outcome":"done","retry":{"attempts":9,"max":5}}}'
rc5=$?
a_attempts_after=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/retry_fixture.json")
[ "$rc5" -ne 0 ] && [ "$a_attempts_after" = "0" ] &&
    ok "retry.attempts > retry.max fails closed, node unchanged" ||
    fail "retry.attempts > retry.max fails closed" "rc=$rc5 attempts_after=$a_attempts_after"

# --- array-typed status must not pass enum membership. jq's index() does
# subsequence search on an array needle, so index(["done"]) would wrongly
# match a valid element -- the guard uses IN() (true membership) instead.
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/array_status_fixture.json"
stamp_identity "$TMP/array_status_fixture.json"
graph_executor_apply_wave "$TMP/array_status_fixture.json" '{"A":{"status":["done"]}}'
rc8=$?
a_status_after_arr=$(jq -c '.graph.nodes.A.status' "$TMP/array_status_fixture.json")
[ "$rc8" -ne 0 ] && [ "$a_status_after_arr" = '"pending"' ] &&
    ok "array-typed status fails closed, node unchanged" ||
    fail "array-typed status fails closed" "rc=$rc8 status_after=$a_status_after_arr"

# --- retry.max above the contract's cap of 5, and negative attempts, must
# both fail closed -- a bare "attempts > max" comparison alone lets both
# slide through (99 > 5 is a valid state under that check; -3 > 5 is false).
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/retry_cap_fixture.json"
stamp_identity "$TMP/retry_cap_fixture.json"
graph_executor_apply_wave "$TMP/retry_cap_fixture.json" '{"A":{"status":"done","outcome":"done","retry":{"attempts":0,"max":99}}}'
rc9=$?
a_max_after=$(jq -r '.graph.nodes.A.retry.max' "$TMP/retry_cap_fixture.json")
[ "$rc9" -ne 0 ] && [ "$a_max_after" = "5" ] &&
    ok "retry.max above the contract cap of 5 fails closed, node unchanged" ||
    fail "retry.max above the contract cap of 5 fails closed" "rc=$rc9 max_after=$a_max_after"

jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/retry_negative_fixture.json"
stamp_identity "$TMP/retry_negative_fixture.json"
graph_executor_apply_wave "$TMP/retry_negative_fixture.json" '{"A":{"status":"done","outcome":"done","retry":{"attempts":-3,"max":5}}}'
rc10=$?
a_attempts_after_neg=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/retry_negative_fixture.json")
[ "$rc10" -ne 0 ] && [ "$a_attempts_after_neg" = "0" ] &&
    ok "negative retry.attempts fails closed, node unchanged" ||
    fail "negative retry.attempts fails closed" "rc=$rc10 attempts_after=$a_attempts_after_neg"

# --- explicit "status": null in a wave-result must not bypass the guard and
# NULL OUT the existing node's valid status (distinguishing "field omitted"
# from "field explicitly null" matters here).
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/null_status_fixture.json"
stamp_identity "$TMP/null_status_fixture.json"
graph_executor_apply_wave "$TMP/null_status_fixture.json" '{"A":{"status":null}}'
rc11=$?
a_status_after_null=$(jq -c '.graph.nodes.A.status' "$TMP/null_status_fixture.json")
[ "$rc11" -ne 0 ] && [ "$a_status_after_null" = '"pending"' ] &&
    ok "explicit status:null fails closed, existing status not nulled out" ||
    fail "explicit status:null fails closed" "rc=$rc11 status_after=$a_status_after_null"

# --- id-existence check must read LIVE file state under the lock, not a
# pre-lock snapshot (TOCTOU). Simulate a node already having been
# removed by a prior writer by the time apply_wave's own locked jq runs —
# there is no separate pre-lock read to go stale, since the check lives
# inside the same jq program that performs the write.
jq -n '{ graph: { nodes: {}, edges: [], joins: {} }, decisions_absorbed: [] }' >"$TMP/race_fixture.json"
stamp_identity "$TMP/race_fixture.json"
graph_executor_apply_wave "$TMP/race_fixture.json" '{"A":{"status":"done","outcome":"done"}}'
rc6=$?
a_created=$(jq 'has("A")' <(jq '.graph.nodes' "$TMP/race_fixture.json"))
[ "$rc6" -ne 0 ] && [ "$a_created" = "false" ] &&
    ok "id-existence check reads live file state (no pre-lock snapshot to race)" ||
    fail "id-existence check reads live file state" "rc=$rc6 created=$a_created"

# --- S5: a non-object node value (e.g. a bare string) must never clobber
# an existing node's fields; als_atomic_progress_update's jq errors on the
# `*` merge against a non-object, so no write attempt lands.
jq -n '
  { graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} },
             edges: [], joins: {} },
    decisions_absorbed: [] }
' >"$TMP/s5_fixture.json"
stamp_identity "$TMP/s5_fixture.json"
graph_executor_apply_wave "$TMP/s5_fixture.json" '{"A":"clobbered"}'
rc7=$?
a_after_s5=$(jq -c '.graph.nodes.A' "$TMP/s5_fixture.json")
[ "$rc7" -ne 0 ] && [ "$a_after_s5" = '{"status":"pending","outcome":"pending","retry":{"attempts":0,"max":5},"evidence":[]}' ] &&
    ok "non-object node value fails closed, existing node untouched" ||
    fail "non-object node value fails closed" "rc=$rc7 a_after=$a_after_s5"

# --- S4: ready_nodes fails closed on unparseable progress.json (symmetry
# with graph_readiness.sh and apply_wave, both of which fail closed on the
# same input) instead of silently reporting zero ready nodes.
printf 'not json' >"$TMP/corrupt.json"
ready3=$(graph_executor_ready_nodes "$TMP/corrupt.json")
rc_corrupt=$?
[ "$rc_corrupt" -ne 0 ] && [ -z "$ready3" ] &&
    ok "ready_nodes fails closed on unparseable progress.json" ||
    fail "ready_nodes fails closed on unparseable progress.json" "rc=$rc_corrupt out=$ready3"

# --- S4 control: a valid file with an empty (zero-node) graph is NOT an
# error -- must still return 0 with empty output, distinct from corrupt-JSON.
jq -n '{ graph: { nodes: {}, edges: [], joins: {} } }' >"$TMP/empty_nodes.json"
stamp_identity "$TMP/empty_nodes.json"
ready4=$(graph_executor_ready_nodes "$TMP/empty_nodes.json")
rc_empty=$?
[ "$rc_empty" -eq 0 ] && [ -z "$ready4" ] &&
    ok "ready_nodes returns 0 on a valid empty-nodes graph (negative control of the corrupt-JSON case)" ||
    fail "ready_nodes returns 0 on a valid empty-nodes graph" "rc=$rc_empty out=$ready4"

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
