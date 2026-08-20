#!/bin/bash
# shellcheck disable=SC2015  # test assertions intentionally use condition && ok || fail
# Tests for graph_dispatch.sh (Claude-provider dispatch layer on top of
# graph_executor.sh/graph_readiness.sh, reused verbatim). Covers:
#   1. plan: ready-wave computation resolves each ready node's graph_role
#      through the Claude plugin's fixed role map.
#   2. plan: an unmapped graph_role fails closed as unresolved, never
#      guesses.
#   3. record: a "failed" outcome increments retry.attempts and keeps the
#      affected node in play ("running") while attempts < max.
#   4. record: retry.max reached -> "hard-stop", not another retry.
#   5. record: resume — a done/hard-stop node is never re-listed by
#      graph_executor_ready_nodes (reused, not reimplemented).
#   6. record: stale contract (stale_check requirement) still holds
#      through the wrapper, unmodified from graph_executor_apply_wave.
#   7. record: exactly ONE als_atomic_progress_update call per wave (same
#      AC-8/D1 collect-before-write guarantee graph_executor.sh gives,
#      still true through this wrapper).
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

# shellcheck disable=SC1091  # library path is resolved from this test file at runtime
. "$LIB_DIR/graph_dispatch.sh"

stamp_identity() {
    local path="$1"
    jq '. + {session_id:"session-test",loop_id:"loop-test",revision:1}' "$path" >"$path.tmp" && mv "$path.tmp" "$path"
}

begin_wave() {
    stamp_identity "$1"
    graph_dispatch_begin_wave "$1" >/dev/null
}

record_active_wave() {
    local progress="$1" results="$2" wave_id envelope
    wave_id=$(jq -r '.graph.active_wave.wave_id' "$progress")
    envelope=$(jq -cn --arg wave_id "$wave_id" --argjson results "$results" \
        '{wave_id:$wave_id,results:$results}')
    graph_dispatch_record "$progress" "$envelope"
}

# --- 1: plan resolves a ready node with an unambiguous graph_role ---
jq -n '
  { graph: { nodes: {
      S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}, graph_role:"S2"},
      "S2.5": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}, graph_role:"S2.5"}
    }, edges: [{from:"S2",to:"S2.5"}], joins: {} } }
' >"$TMP/plan1.json"
stamp_identity "$TMP/plan1.json"
out=$(graph_dispatch_plan "$TMP/plan1.json")
skill_id=$(printf '%s' "$out" | jq -r 'select(.node_id=="S2.5") | .skill_id')
unresolved=$(printf '%s' "$out" | jq -r 'select(.node_id=="S2.5") | .unresolved')
[ "$skill_id" = "design-scout" ] && [ "$unresolved" = "false" ] &&
    ok "plan resolves S2.5 -> design-scout (agent)" ||
    fail "plan resolves S2.5 -> design-scout" "skill_id=$skill_id unresolved=$unresolved"

# --- 2: plan fails closed on an unmapped graph_role ---
jq -n '
  { graph: { nodes: {
      S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}, graph_role:"S2"},
      "U4b-review": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}, graph_role:"U4b-review"}
    }, edges: [{from:"S2",to:"U4b-review"}], joins: {} } }
' >"$TMP/plan2.json"
stamp_identity "$TMP/plan2.json"
out=$(graph_dispatch_plan "$TMP/plan2.json")
unresolved=$(printf '%s' "$out" | jq -r 'select(.node_id=="U4b-review") | .unresolved')
skill_id=$(printf '%s' "$out" | jq -r 'select(.node_id=="U4b-review") | .skill_id')
[ "$unresolved" = "true" ] && [ "$skill_id" = "null" ] &&
    ok "plan fails closed on unmapped graph_role, never guesses a target" ||
    fail "plan fails closed on unmapped graph_role" "unresolved=$unresolved skill_id=$skill_id"

# --- 3: record — failed outcome increments attempts, stays in play ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:2}} }, edges: [], joins: {} } }' >"$TMP/f3.json"
begin_wave "$TMP/f3.json"
record_active_wave "$TMP/f3.json" '{"A":{"outcome":"failed","provider":"claude","skill_id":"loop-worker"}}'
rc3=$?
status3=$(jq -r '.graph.nodes.A.status' "$TMP/f3.json")
attempts3=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/f3.json")
[ "$rc3" -eq 0 ] && [ "$status3" = "pending" ] && [ "$attempts3" = "1" ] &&
    ok "record: failed outcome increments attempts (0->1), node returns to pending" ||
    fail "record: failed outcome increments attempts" "rc=$rc3 status=$status3 attempts=$attempts3"

# --- 4: record — retry.max reached -> hard-stop ---
begin_wave "$TMP/f3.json"
record_active_wave "$TMP/f3.json" '{"A":{"outcome":"failed","provider":"claude","skill_id":"loop-worker"}}'
rc4=$?
status4=$(jq -r '.graph.nodes.A.status' "$TMP/f3.json")
attempts4=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/f3.json")
[ "$rc4" -eq 0 ] && [ "$status4" = "hard-stop" ] && [ "$attempts4" = "2" ] &&
    ok "record: retry.max reached (2/2) -> hard-stop, not another retry" ||
    fail "record: retry.max reached -> hard-stop" "rc=$rc4 status=$status4 attempts=$attempts4"

# --- 5: resume — a hard-stop node is never re-listed as ready; a done
# graph entry is never re-listed as ready either ---
ready5=$(graph_executor_ready_nodes "$TMP/f3.json")
[ -z "$ready5" ] && ok "resume: hard-stop node A not re-listed by graph_executor_ready_nodes" ||
    fail "resume: hard-stop node not re-listed" "ready5=$ready5"

jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f5b.json"
begin_wave "$TMP/f5b.json"
record_active_wave "$TMP/f5b.json" '{"A":{"outcome":"done","provider":"claude","skill_id":"loop-worker","evidence":"PR #999"}}' >/dev/null
ready5b=$(graph_executor_ready_nodes "$TMP/f5b.json")
[ -z "$ready5b" ] && ok "resume: done node A not re-listed by graph_executor_ready_nodes" ||
    fail "resume: done node not re-listed" "ready5b=$ready5b"

# --- 6: stale contract still enforced through the wrapper ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f6.json"
begin_wave "$TMP/f6.json"
record_active_wave "$TMP/f6.json" '{"A":{"status":"stale","outcome":"stale"}}'
rc6a=$?
[ "$rc6a" -ne 0 ] && ok "record: bare stale (no stale_check) refused through the wrapper" ||
    fail "record: bare stale refused" "rc=$rc6a"

record_active_wave "$TMP/f6.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":true,"method":"gh pr view","result":"no PR found"}}}'
rc6b=$?
status6b=$(jq -r '.graph.nodes.A.status' "$TMP/f6.json")
[ "$rc6b" -eq 0 ] && [ "$status6b" = "stale" ] &&
    ok "record: stale WITH valid stale_check succeeds through the wrapper" ||
    fail "record: stale with valid stale_check succeeds" "rc=$rc6b status=$status6b"

# --- 7: exactly ONE als_atomic_progress_update call per graph_dispatch_record ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}}, B:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f7.json"
begin_wave "$TMP/f7.json"
CALL_LOG="$TMP/calls.log"
: >"$CALL_LOG"
eval "$(declare -f als_atomic_progress_update | sed '1s/als_atomic_progress_update/__real_als_atomic_progress_update/')"
als_atomic_progress_update() {
    echo "call" >>"$CALL_LOG"
    __real_als_atomic_progress_update "$@"
}
record_active_wave "$TMP/f7.json" '{"A":{"outcome":"done","provider":"claude"},"B":{"outcome":"done","provider":"claude"}}' >/dev/null
call_count=$(wc -l <"$CALL_LOG" | tr -d ' ')
[ "$call_count" = "1" ] && ok "record: exactly ONE als_atomic_progress_update call for a 2-node wave" ||
    fail "record: exactly ONE write per wave" "call_count=$call_count"

# --- 8: plan resolves a ready node via node-id FALLBACK when no explicit
# graph_role field is seeded (current graph seeds use
# status/outcome/retry only) ---
jq -n '
  { graph: { nodes: {
      S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}},
      "S2.5": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
    }, edges: [{from:"S2",to:"S2.5"}], joins: {} } }
' >"$TMP/plan8.json"
stamp_identity "$TMP/plan8.json"
out=$(graph_dispatch_plan "$TMP/plan8.json")
skill_id=$(printf '%s' "$out" | jq -r 'select(.node_id=="S2.5") | .skill_id')
[ "$skill_id" = "design-scout" ] &&
    ok "plan resolves S2.5 -> design-scout via node-id fallback (no explicit graph_role field)" ||
    fail "plan resolves via node-id fallback" "skill_id=$skill_id"

# --- 9: plan reports a join node as kind:"join", distinct from a
# genuinely-unresolvable node (J2 is absorbed by the orchestrator,
# never dispatched) ---
jq -n '
  { graph: { nodes: {
      "S2.5": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
      "S2.6": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
      J2: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
    }, edges: [{from:"S2.5",to:"J2"},{from:"S2.6",to:"J2"}],
       joins: {J2:{id:"J2",mode:"all",inputs:["S2.5","S2.6"]}} } }
' >"$TMP/plan9.json"
stamp_identity "$TMP/plan9.json"
out=$(graph_dispatch_plan "$TMP/plan9.json")
kind9=$(printf '%s' "$out" | jq -r 'select(.node_id=="J2") | .kind')
unresolved9=$(printf '%s' "$out" | jq -r 'select(.node_id=="J2") | .unresolved')
[ "$kind9" = "join" ] && [ "$unresolved9" = "false" ] &&
    ok "plan reports a ready join node as kind:join, not unresolved" ||
    fail "plan reports join node as kind:join" "kind=$kind9 unresolved=$unresolved9"

# --- 10: record — a "done" result reported via "status" only (no
# "outcome" key) must land as done, never silently miscast as a failed
# retry (regression: review found `$r.outcome // "failed"` treated a
# missing outcome key as a reported failure) ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f10.json"
begin_wave "$TMP/f10.json"
record_active_wave "$TMP/f10.json" '{"A":{"status":"done","provider":"claude","evidence":"PR #1"}}'
rc10=$?
status10=$(jq -r '.graph.nodes.A.status' "$TMP/f10.json")
attempts10=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/f10.json")
[ "$rc10" -eq 0 ] && [ "$status10" = "done" ] && [ "$attempts10" = "0" ] &&
    ok "record: status-only done result lands as done, not miscast as failed retry" ||
    fail "record: status-only done result" "rc=$rc10 status=$status10 attempts=$attempts10"

# --- 11: record — a "stale" result reported via "status" only still
# requires (and is gated by) stale_check, same as an "outcome":"stale"
# result (regression: the missing-outcome default previously rewrote
# this to "running" before graph_executor_apply_wave's stale_check
# guard ever saw it) ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f11.json"
begin_wave "$TMP/f11.json"
record_active_wave "$TMP/f11.json" '{"A":{"status":"stale"}}'
rc11a=$?
[ "$rc11a" -ne 0 ] && ok "record: status-only stale with no stale_check is refused (not silently rewritten to running)" ||
    fail "record: status-only bare stale refused" "rc=$rc11a"

record_active_wave "$TMP/f11.json" '{"A":{"status":"stale","stale_check":{"checked":true,"method":"gh pr view","result":"no PR found"}}}'
rc11b=$?
status11b=$(jq -r '.graph.nodes.A.status' "$TMP/f11.json")
[ "$rc11b" -eq 0 ] && [ "$status11b" = "stale" ] &&
    ok "record: status-only stale WITH valid stale_check succeeds" ||
    fail "record: status-only stale with valid stale_check" "rc=$rc11b status=$status11b"

# --- 12: record — a result naming NEITHER outcome nor status aborts the
# wave rather than being silently treated as failed ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f12.json"
begin_wave "$TMP/f12.json"
record_active_wave "$TMP/f12.json" '{"A":{"provider":"claude"}}'
rc12=$?
status12=$(jq -r '.graph.nodes.A.status' "$TMP/f12.json")
[ "$rc12" -ne 0 ] && [ "$status12" = "running" ] &&
    ok "record: result naming neither outcome nor status is refused, active wave unchanged" ||
    fail "record: neither outcome nor status refused" "rc=$rc12 status=$status12"

# --- 13: record — attempts is capped at max, so a wave containing a
# failed node re-reporting past its bound does NOT discard a sibling
# node's real result in the same wave (regression: uncapped attempts
# could exceed max, tripping graph_executor_apply_wave's attempts<=max
# contract check INSIDE the lock and rejecting the entire wave) ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:2,max:2}}, B:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f13.json"
begin_wave "$TMP/f13.json"
record_active_wave "$TMP/f13.json" '{"A":{"outcome":"failed"},"B":{"outcome":"done"}}'
rc13=$?
statusA13=$(jq -r '.graph.nodes.A.status' "$TMP/f13.json")
attemptsA13=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/f13.json")
statusB13=$(jq -r '.graph.nodes.B.status' "$TMP/f13.json")
[ "$rc13" -eq 0 ] && [ "$statusA13" = "hard-stop" ] && [ "$attemptsA13" = "2" ] && [ "$statusB13" = "done" ] &&
    ok "record: attempts capped at max, sibling node B's done result survives A re-failing past its bound" ||
    fail "record: attempts capped, sibling survives" "rc=$rc13 A.status=$statusA13 A.attempts=$attemptsA13 B.status=$statusB13"

# --- 14: retry.max:0 is outside the graph contract's 1..5 domain. ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:0}}, B:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' >"$TMP/f14.json"
begin_wave "$TMP/f14.json"
rc14=$?
statusA14=$(jq -r '.graph.nodes.A.status' "$TMP/f14.json")
statusB14=$(jq -r '.graph.nodes.B.status' "$TMP/f14.json")
[ "$rc14" -ne 0 ] && [ "$statusA14" = "pending" ] && [ "$statusB14" = "pending" ] &&
    ok "begin: retry.max:0 is rejected without changing sibling state" ||
    fail "begin: retry.max:0 rejected" "rc=$rc14 A.status=$statusA14 B.status=$statusB14"

[ "$fails" -eq 0 ] && {
    echo "PASS"
    exit 0
} || {
    echo "FAILED ($fails)"
    exit 1
}
