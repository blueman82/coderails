#!/bin/bash
# graph_executor.sh — wave collect-and-write for progress.json's durable
# execution graph (see skills/agentic-loop/loop-state.md's `graph` field
# docs). Per spec.md D1: collects an entire wave's results, then performs
# EXACTLY ONE locked read-modify-write via als_atomic_progress_update's
# jq reduce filter — never one call per node. Dispatch itself (spawning
# agents) is out of scope; this is the collection+write mechanism only.
#
# SOURCED, not executed directly — provides two functions:
#
#   graph_executor_ready_nodes <progress.json path>
#     Enumerates graph.nodes and prints one ready node-id per line, by
#     calling graph_readiness.sh (existing, read-only, reused verbatim)
#     for each. Never writes. Contract: exit 0 always (regardless of how
#     many/few nodes are ready), UNLESS path is missing (exit 1); stdout
#     is the only signal of which nodes are ready.
#
#   graph_executor_apply_wave <progress.json path> <wave-results JSON>
#     wave-results shape: {"<node_id>": {"status":..., "outcome":...,
#     "retry": {...}}, ...}, with an optional sibling top-level key
#     "decisions_absorbed": [{"phase":..., "decision":...}, ...].
#     Folds every node result into .graph.nodes[node_id] (merge, so
#     unspecified existing fields survive) and appends every
#     decisions_absorbed entry, via ONE als_atomic_progress_update call.
#     Returns 1 (no write attempted) if wave-results is not a JSON object,
#     has no node entries, or names any node id not already present in
#     .graph.nodes (fail-closed by design — this function never creates a
#     graph node; a typo'd id must not silently land a partial/invalid
#     node that violates graph_contract.test.sh's required-field enum).
#     Callers wanting a "write bare stale" guard (unit 5 / AC-9) add that
#     validation here, before the als_atomic_progress_update call below.

GRAPH_EXECUTOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./loop_state_common.sh
. "$GRAPH_EXECUTOR_DIR/loop_state_common.sh"

graph_executor_ready_nodes() {
  local path="$1"
  [ -f "$path" ] || return 1
  local node
  jq -r '(.graph.nodes // {}) | keys[]' "$path" 2>/dev/null | while IFS= read -r node; do
    [ "$(bash "$GRAPH_EXECUTOR_DIR/graph_readiness.sh" "$path" "$node")" = "ready" ] && printf '%s\n' "$node"
  done
  return 0
}

graph_executor_apply_wave() {
  local path="$1" wave_json="$2"
  [ -f "$path" ] || return 1

  # Fail closed: wave_json must be an object with at least one node-result
  # key, and every such key must already exist in .graph.nodes (this
  # function never creates nodes — see header contract note).
  printf '%s' "$wave_json" | jq -e --slurpfile pf "$path" '
    . as $wave
    | ($pf[0].graph.nodes // {}) as $existing
    | (type == "object")
      and ((keys - ["decisions_absorbed"]) | length > 0)
      and ((keys - ["decisions_absorbed"]) | all(. as $id | $existing | has($id)))
  ' >/dev/null 2>&1 || return 1

  als_atomic_progress_update "$path" \
    --argjson wave "$wave_json" '
    (.graph.nodes // {}) as $nodes
    | ($wave | del(.decisions_absorbed)) as $results
    | .graph.nodes = ($results | reduce keys[] as $id ($nodes;
        .[$id] = (($nodes[$id] // {}) * $results[$id])
      ))
    | .decisions_absorbed = ((.decisions_absorbed // []) + ($wave.decisions_absorbed // []))
  '
}
