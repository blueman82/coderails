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
#     for each. Never writes. Contract: exit 0 (regardless of how many/few
#     nodes are ready), UNLESS path is missing OR unparseable (exit 1, no
#     stdout) — fails closed on a corrupt file the same way apply_wave
#     does, rather than silently reporting zero ready nodes.
#
#   graph_executor_apply_wave <progress.json path> <wave-results JSON>
#     wave-results shape: {"<node_id>": {"status":..., "outcome":...,
#     "retry": {...}}, ...}, with an optional sibling top-level key
#     "decisions_absorbed": [{"phase":..., "decision":...}, ...].
#     Folds every node result into .graph.nodes[node_id] (merge, so
#     unspecified existing fields survive) and appends every
#     decisions_absorbed entry, via ONE als_atomic_progress_update call.
#     Returns 1 (no write attempted) if wave-results is not a JSON object,
#     has no node entries, names any node id not already present in
#     .graph.nodes, or gives any node a status/outcome/retry violating
#     graph_contract.test.sh's own contract (status/outcome must be in its
#     enum via IN()-membership — not jq's index(), which does subsequence
#     search and would wrongly accept an array like ["done"]; retry.attempts
#     and retry.max must both be numbers, attempts >= 0, max in 0..5,
#     attempts <= max) — the exact predicate is lifted from that test, not
#     re-derived, so this guard can't drift weaker than it. Also rejects a
#     bare "stale" write: any node whose merged status OR outcome is
#     "stale" must carry a sibling stale_check field shaped
#     {"checked":true,"method":"<string>","result":"<string>"} (both
#     strings non-empty) in the SAME wave-result — per loop-state.md's
#     stale field docs, idle is not evidence, it must be paired with an
#     artifact check (fail-closed by design — this function never creates
#     a graph node, and never lands a value that violates the graph's own
#     contract).
#     ALL validation, including the id-existence check, runs INSIDE the
#     locked jq filter via jq's error(...) (which aborts the filter, so
#     als_atomic_progress_update's `mv` never runs) — not via a pre-lock
#     read — because a pre-lock read-then-decide is a TOCTOU race: another
#     writer can delete/mutate a node between the check and the locked
#     write. See als_atomic_progress_update's own mkdir-lock (loop_state_common.sh).

GRAPH_EXECUTOR_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./loop_state_common.sh
. "$GRAPH_EXECUTOR_DIR/loop_state_common.sh"

graph_executor_ready_nodes() {
  local path="$1"
  [ -f "$path" ] || return 1
  local node
  jq -e -r '(.graph.nodes // {}) | keys[]' "$path" 2>/dev/null | while IFS= read -r node; do
    [ "$(bash "$GRAPH_EXECUTOR_DIR/graph_readiness.sh" "$path" "$node")" = "ready" ] && printf '%s\n' "$node"
  done
  local jq_rc="${PIPESTATUS[0]}"
  [ "$jq_rc" -eq 0 ] || [ "$jq_rc" -eq 4 ] || return 1
  return 0
}

graph_executor_apply_wave() {
  local path="$1" wave_json="$2"
  [ -f "$path" ] || return 1

  # Cheap shape check outside the lock (not a security/race boundary — just
  # avoids taking the lock for an obviously-malformed input). The
  # authoritative check, including id-existence, is the jq program below,
  # which runs INSIDE als_atomic_progress_update's lock against the
  # freshly-read file, so nothing checked here needs to be trusted twice.
  printf '%s' "$wave_json" | jq -e '
    type == "object" and ((keys - ["decisions_absorbed"]) | length > 0)
  ' >/dev/null 2>&1 || return 1

  # Enum/retry predicate lifted verbatim from graph_contract.test.sh (same
  # IN()-membership and 4-constraint retry check that test already enforces
  # on a written file) — not re-derived, so this guard can't drift weaker
  # than the contract it's supposed to uphold. IN() (not index()) is
  # required: jq's index() does subsequence search on an array needle, so
  # index() would wrongly accept status:["done"] as valid; IN() is true
  # membership and also correctly rejects an explicit null.
  als_atomic_progress_update "$path" \
    --argjson wave "$wave_json" '
    (.graph.nodes // {}) as $nodes
    | ($wave | del(.decisions_absorbed)) as $results
    | .graph.nodes = ($results | reduce keys[] as $id ($nodes;
        if ($nodes | has($id) | not) then
          error("graph_executor: unknown node id \($id), refusing to create")
        else
          (($nodes[$id] // {}) * $results[$id]) as $merged
          | .[$id] = (
              if ($merged.status // null | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
              then error("graph_executor: node \($id) has invalid status \($merged.status)")
              elif ($merged.outcome // null | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
              then error("graph_executor: node \($id) has invalid outcome \($merged.outcome)")
              elif ($merged.retry.attempts | type != "number" or . < 0)
              then error("graph_executor: node \($id) has invalid retry.attempts \($merged.retry.attempts)")
              elif ($merged.retry.max | type != "number" or . < 0 or . > 5)
              then error("graph_executor: node \($id) has invalid retry.max \($merged.retry.max)")
              elif ($merged.retry.attempts > $merged.retry.max)
              then error("graph_executor: node \($id) has retry.attempts > retry.max")
              elif (($merged.status == "stale" or $merged.outcome == "stale")
                    and (($results[$id].stale_check | type) != "object"
                         or $results[$id].stale_check.checked != true
                         or (($results[$id].stale_check.method | type) != "string" or ($results[$id].stale_check.method | length) == 0)
                         or (($results[$id].stale_check.result | type) != "string" or ($results[$id].stale_check.result | length) == 0)))
              then error("graph_executor: node \($id) writes stale without a valid stale_check in THIS wave own result (an old stale_check surviving from a prior wave merge does not count)")
              else $merged
              end
            )
        end
      ))
    | .decisions_absorbed = ((.decisions_absorbed // []) + ($wave.decisions_absorbed // []))
  '
}
