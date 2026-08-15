#!/bin/bash
# Tests for graph_dispatch.sh (Claude-provider dispatch layer on top of
# graph_executor.sh/graph_readiness.sh, reused verbatim). Covers:
#   1. plan: ready-wave computation resolves each ready node's graph_role
#      via skills/index.yaml to a real dispatch target.
#   2. plan: an ambiguous graph_role (>1 match within the winning
#      source_kind precedence tier) fails closed as unresolved, never
#      guesses.
#   3. record: a "failed" outcome increments retry.attempts and keeps the
#      node in play ("running") while attempts < max.
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
REPO_ROOT="$(cd "$LIB_DIR/../../.." && pwd)"
INDEX_YAML="$REPO_ROOT/skills/index.yaml"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
ok() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n      %s\n' "$1" "$2"; fails=$((fails+1)); }

. "$LIB_DIR/graph_dispatch.sh"

[ -f "$INDEX_YAML" ] || { echo "FATAL: skills/index.yaml not found at $INDEX_YAML"; exit 1; }

# --- 1: plan resolves a ready node with an unambiguous graph_role ---
jq -n '
  { graph: { nodes: {
      S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}, graph_role:"S2"},
      "S2.5": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}, graph_role:"S2.5"}
    }, edges: [{from:"S2",to:"S2.5"}], joins: {} } }
' > "$TMP/plan1.json"
out=$(graph_dispatch_plan "$TMP/plan1.json" "$INDEX_YAML")
skill_id=$(printf '%s' "$out" | jq -r 'select(.node_id=="S2.5") | .skill_id')
unresolved=$(printf '%s' "$out" | jq -r 'select(.node_id=="S2.5") | .unresolved')
[ "$skill_id" = "design-scout" ] && [ "$unresolved" = "false" ] \
  && ok "plan resolves S2.5 -> design-scout (agent)" \
  || fail "plan resolves S2.5 -> design-scout" "skill_id=$skill_id unresolved=$unresolved"

# --- 2: plan fails closed on an ambiguous graph_role (U4b-review has two
# agent-tier matches: deploy-safety-reviewer, source-auditor) ---
jq -n '
  { graph: { nodes: {
      S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}, graph_role:"S2"},
      "U4b-review": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}, graph_role:"U4b-review"}
    }, edges: [{from:"S2",to:"U4b-review"}], joins: {} } }
' > "$TMP/plan2.json"
out=$(graph_dispatch_plan "$TMP/plan2.json" "$INDEX_YAML")
unresolved=$(printf '%s' "$out" | jq -r 'select(.node_id=="U4b-review") | .unresolved')
skill_id=$(printf '%s' "$out" | jq -r 'select(.node_id=="U4b-review") | .skill_id')
[ "$unresolved" = "true" ] && [ "$skill_id" = "null" ] \
  && ok "plan fails closed on ambiguous graph_role, never guesses a target" \
  || fail "plan fails closed on ambiguous graph_role" "unresolved=$unresolved skill_id=$skill_id"

# --- 3: record — failed outcome increments attempts, stays in play ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:2}} }, edges: [], joins: {} } }' > "$TMP/f3.json"
graph_dispatch_record "$TMP/f3.json" '{"A":{"outcome":"failed","provider":"claude","skill_id":"loop-worker"}}'
rc3=$?
status3=$(jq -r '.graph.nodes.A.status' "$TMP/f3.json")
attempts3=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/f3.json")
[ "$rc3" -eq 0 ] && [ "$status3" = "running" ] && [ "$attempts3" = "1" ] \
  && ok "record: failed outcome increments attempts (0->1), node stays running" \
  || fail "record: failed outcome increments attempts" "rc=$rc3 status=$status3 attempts=$attempts3"

# --- 4: record — retry.max reached -> hard-stop ---
graph_dispatch_record "$TMP/f3.json" '{"A":{"outcome":"failed","provider":"claude","skill_id":"loop-worker"}}'
rc4=$?
status4=$(jq -r '.graph.nodes.A.status' "$TMP/f3.json")
attempts4=$(jq -r '.graph.nodes.A.retry.attempts' "$TMP/f3.json")
[ "$rc4" -eq 0 ] && [ "$status4" = "hard-stop" ] && [ "$attempts4" = "2" ] \
  && ok "record: retry.max reached (2/2) -> hard-stop, not another retry" \
  || fail "record: retry.max reached -> hard-stop" "rc=$rc4 status=$status4 attempts=$attempts4"

# --- 5: resume — a hard-stop node is never re-listed as ready; a done
# node is never re-listed as ready either ---
ready5=$(graph_executor_ready_nodes "$TMP/f3.json")
[ -z "$ready5" ] && ok "resume: hard-stop node A not re-listed by graph_executor_ready_nodes" \
  || fail "resume: hard-stop node not re-listed" "ready5=$ready5"

jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' > "$TMP/f5b.json"
graph_dispatch_record "$TMP/f5b.json" '{"A":{"outcome":"done","provider":"claude","skill_id":"loop-worker","evidence":"PR #999"}}' >/dev/null
ready5b=$(graph_executor_ready_nodes "$TMP/f5b.json")
[ -z "$ready5b" ] && ok "resume: done node A not re-listed by graph_executor_ready_nodes" \
  || fail "resume: done node not re-listed" "ready5b=$ready5b"

# --- 6: stale contract still enforced through the wrapper ---
jq -n '{ graph: { nodes: { A:{status:"running",outcome:"running",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' > "$TMP/f6.json"
graph_dispatch_record "$TMP/f6.json" '{"A":{"status":"stale","outcome":"stale"}}'
rc6a=$?
[ "$rc6a" -ne 0 ] && ok "record: bare stale (no stale_check) refused through the wrapper" \
  || fail "record: bare stale refused" "rc=$rc6a"

graph_dispatch_record "$TMP/f6.json" '{"A":{"status":"stale","outcome":"stale","stale_check":{"checked":true,"method":"gh pr view","result":"no PR found"}}}'
rc6b=$?
status6b=$(jq -r '.graph.nodes.A.status' "$TMP/f6.json")
[ "$rc6b" -eq 0 ] && [ "$status6b" = "stale" ] \
  && ok "record: stale WITH valid stale_check succeeds through the wrapper" \
  || fail "record: stale with valid stale_check succeeds" "rc=$rc6b status=$status6b"

# --- 7: exactly ONE als_atomic_progress_update call per graph_dispatch_record ---
jq -n '{ graph: { nodes: { A:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}}, B:{status:"pending",outcome:"pending",retry:{attempts:0,max:5}} }, edges: [], joins: {} } }' > "$TMP/f7.json"
CALL_LOG="$TMP/calls.log"
: > "$CALL_LOG"
eval "$(declare -f als_atomic_progress_update | sed '1s/als_atomic_progress_update/__real_als_atomic_progress_update/')"
als_atomic_progress_update() {
  echo "call" >> "$CALL_LOG"
  __real_als_atomic_progress_update "$@"
}
graph_dispatch_record "$TMP/f7.json" '{"A":{"outcome":"done","provider":"claude"},"B":{"outcome":"done","provider":"claude"}}' >/dev/null
call_count=$(wc -l < "$CALL_LOG" | tr -d ' ')
[ "$call_count" = "1" ] && ok "record: exactly ONE als_atomic_progress_update call for a 2-node wave" \
  || fail "record: exactly ONE write per wave" "call_count=$call_count"

# --- 8: plan resolves a ready node via node-id FALLBACK when no explicit
# graph_role field is seeded (matches how codex/runtime/graph.py's
# build_graph() actually seeds nodes today: status/outcome/retry only) ---
jq -n '
  { graph: { nodes: {
      S2: {status:"done", outcome:"done", retry:{attempts:0,max:5}},
      "S2.5": {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
    }, edges: [{from:"S2",to:"S2.5"}], joins: {} } }
' > "$TMP/plan8.json"
out=$(graph_dispatch_plan "$TMP/plan8.json" "$INDEX_YAML")
skill_id=$(printf '%s' "$out" | jq -r 'select(.node_id=="S2.5") | .skill_id')
[ "$skill_id" = "design-scout" ] \
  && ok "plan resolves S2.5 -> design-scout via node-id fallback (no explicit graph_role field)" \
  || fail "plan resolves via node-id fallback" "skill_id=$skill_id"

# --- 9: plan reports a join node as kind:"join", distinct from a
# genuinely-unresolvable node (J2 has no skills/index.yaml entry by
# design — it's absorbed by the orchestrator, never dispatched) ---
jq -n '
  { graph: { nodes: {
      "S2.5": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
      "S2.6": {status:"done", outcome:"done", retry:{attempts:0,max:5}},
      J2: {status:"pending", outcome:"pending", retry:{attempts:0,max:5}}
    }, edges: [{from:"S2.5",to:"J2"},{from:"S2.6",to:"J2"}],
       joins: {J2:{id:"J2",mode:"all",inputs:["S2.5","S2.6"]}} } }
' > "$TMP/plan9.json"
out=$(graph_dispatch_plan "$TMP/plan9.json" "$INDEX_YAML")
kind9=$(printf '%s' "$out" | jq -r 'select(.node_id=="J2") | .kind')
unresolved9=$(printf '%s' "$out" | jq -r 'select(.node_id=="J2") | .unresolved')
[ "$kind9" = "join" ] && [ "$unresolved9" = "false" ] \
  && ok "plan reports a ready join node as kind:join, not unresolved" \
  || fail "plan reports join node as kind:join" "kind=$kind9 unresolved=$unresolved9"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
