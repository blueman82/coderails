#!/bin/bash
# shellcheck disable=SC1091,SC2016 # Runtime-resolved sources and literal jq programs are intentional.
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

graph_executor_graph_valid() {
    local path="$1"
    jq -e '
      .graph as $g
      | ($g.nodes) as $nodes
      | ($g.edges) as $edges
      | ($g.joins) as $joins
      | ($g.active_wave) as $active
      | ($g.hard_stop) as $hard_stop
      | ($edges + [$joins | to_entries[] as $join
                    | $join.value.inputs[]? | {from:.,to:$join.key}]) as $dependencies
      | ($g | type) == "object"
        and ($nodes | type) == "object"
        and ($edges | type) == "array"
        and ($joins | type) == "object"
        and ([$nodes | to_entries[]
              | select((.value | type) != "object"
                       or (.value.status | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
                       or (.value.outcome | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
                       or .value.status != .value.outcome
                       or (.value.retry.attempts | type) != "number"
                       or (.value.retry.max | type) != "number"
                       or .value.retry.attempts < 0
                       or .value.retry.max < 0
                       or .value.retry.max > 5
                       or .value.retry.attempts > .value.retry.max)] | length) == 0
        and ([$edges[] as $edge
              | select(($edge | type) != "object"
                       or ($edge.from | type) != "string"
                       or ($edge.to | type) != "string"
                       or ($nodes | has($edge.from) | not)
                       or ($nodes | has($edge.to) | not))] | length) == 0
        and ([$joins | to_entries[] as $join
              | select(($nodes | has($join.key) | not)
                       or ($join.value | type) != "object"
                       or $join.value.mode != "all"
                       or ($join.value.inputs | type) != "array"
                       or ($join.value.inputs | length) == 0
                       or ([$join.value.inputs[] as $input
                            | select(($input | type) != "string" or ($nodes | has($input) | not))] | length) != 0
                       or (($join.value | has("released")) and ($join.value.released | type) != "boolean"))] | length) == 0
        and ($hard_stop == null or ($hard_stop | type) == "object")
        and (($active == null)
             or (($active | type) == "object"
                 and ($active.wave_id | type) == "string"
                 and ($active.wave_id | length) > 0
                 and ($active.revision | type) == "number"
                 and ($active.nodes | type) == "array"
                 and ($active.nodes | length) > 0
                 and ($active.nodes | unique | length) == ($active.nodes | length)
                 and ([$active.nodes[] as $id
                       | select(($id | type) != "string" or ($nodes | has($id) | not))] | length) == 0))
        and (([$nodes | to_entries[] | select(.value.status == "running") | .key] | sort)
             == (if $active == null then [] else ($active.nodes | sort) end))
        and (((reduce range(0; ($nodes | length)) as $i ($dependencies;
                  . + [.[] as $left
                       | .[] as $right
                       | select($left.to == $right.from)
                       | {from:$left.from,to:$right.to}]
                  | unique_by([.from,.to])))
              | any(.from == .to)) | not)
    ' "$path" >/dev/null 2>&1
}

graph_executor_ready_nodes() {
    local path="$1"
    [ -f "$path" ] || return 1
    graph_executor_graph_valid "$path" || return 1
    local node
    jq -e -r '(.graph.nodes // {}) | keys[]' "$path" 2>/dev/null | while IFS= read -r node; do
        [ "$(bash "$GRAPH_EXECUTOR_DIR/graph_readiness.sh" "$path" "$node")" = "ready" ] && printf '%s\n' "$node"
    done
    local jq_rc="${PIPESTATUS[0]}"
    [ "$jq_rc" -eq 0 ] || [ "$jq_rc" -eq 4 ] || return 1
    return 0
}

graph_executor_apply_wave() {
    local path="$1" wave_json="$2" wave_id="${3:-}"
    [ -f "$path" ] || return 1
    printf '%s' "$wave_json" | jq -e '
    type == "object" and ((keys - ["decisions_absorbed"]) | length > 0)
  ' >/dev/null 2>&1 || return 1
    als_atomic_progress_update "$path" \
        --argjson wave "$wave_json" --arg wave_id "$wave_id" '
    (.graph.nodes // {}) as $nodes
    | ($wave | del(.decisions_absorbed)) as $results
    | (.graph.active_wave) as $active | (.graph.hard_stop) as $hard_stop
    | (.graph.edges + [.graph.joins | to_entries[] as $join | $join.value.inputs[]? | {from:.,to:$join.key}]) as $dependencies
    | ($active != null) as $tracked_wave
    | if ((.graph | type) != "object"
          or ($nodes | type) != "object"
          or ((.graph.edges // null) | type) != "array"
          or ((.graph.joins // null) | type) != "object"
          or ([$nodes | to_entries[] | select((.value | type) != "object"
                        or (.value.status | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
                        or (.value.outcome | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
                        or .value.status != .value.outcome or (.value.retry.attempts | type) != "number" or (.value.retry.max | type) != "number"
                        or .value.retry.attempts < 0 or .value.retry.max < 0 or .value.retry.max > 5 or .value.retry.attempts > .value.retry.max)] | length) != 0
          or ([.graph.edges[] as $edge | select(($edge | type) != "object" or ($edge.from | type) != "string" or ($edge.to | type) != "string"
                        or ($nodes | has($edge.from) | not) or ($nodes | has($edge.to) | not))] | length) != 0
          or ([.graph.joins | to_entries[] as $join | select(($nodes | has($join.key) | not) or ($join.value | type) != "object"
                        or $join.value.mode != "all" or ($join.value.inputs | type) != "array" or ($join.value.inputs | length) == 0
                        or ([$join.value.inputs[] as $input
                             | select(($input | type) != "string" or ($nodes | has($input) | not))] | length) != 0
                        or (($join.value | has("released")) and ($join.value.released | type) != "boolean"))] | length) != 0
          or ($hard_stop != null and (($hard_stop | type) != "object"))
          or (($active != null) and (($active | type) != "object" or ($active.wave_id | type) != "string" or ($active.wave_id | length) == 0
                   or ($active.revision | type) != "number" or ($active.nodes | type) != "array" or ($active.nodes | length) == 0 or ($active.nodes | unique | length) != ($active.nodes | length)
                   or ([$active.nodes[] as $id
                        | select(($id | type) != "string" or ($nodes | has($id) | not))] | length) != 0))
          or (([$nodes | to_entries[] | select(.value.status == "running") | .key] | sort)
              != (if $active == null then [] else ($active.nodes | sort) end))
          or ((reduce range(0; ($nodes | length)) as $i ($dependencies;
                 . + [.[] as $left | .[] as $right | select($left.to == $right.from) | {from:$left.from,to:$right.to}]
                 | unique_by([.from,.to])))
              | any(.from == .to)))
      then error("graph_executor: malformed graph") elif ($tracked_wave
            and ((.graph.active_wave | type) != "object"
                 or $wave_id == ""
                 or .graph.active_wave.wave_id != $wave_id
                 or (.graph.active_wave.nodes | type) != "array"
                 or ((.graph.active_wave.nodes | sort) != ($results | keys | sort))))
      then error("graph_executor: results must exactly match the active wave") else .
      end
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
              elif ($merged.status != $merged.outcome)
              then error("graph_executor: node \($id) status and outcome disagree")
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
    | if $tracked_wave then
        (.graph.nodes) as $updated_nodes
        |
        .graph.joins = (reduce (.graph.joins | keys[]) as $join (.graph.joins;
          if ((.[$join].released // false) == false
              and (.[$join].inputs | all(. as $input
                    | ($updated_nodes[$input].outcome // "") | IN("done","skipped"))))
          then .[$join].released = true
          else .
          end))
        | .graph.nodes = (reduce (.graph.joins | to_entries[]
                                  | select(.value.released == true) | .key) as $join (.graph.nodes;
            .[$join].status = "done" | .[$join].outcome = "done"))
        | .graph.active_wave = null
        | .revision = ((.revision // 0) + 1)
        | ([.graph.nodes | to_entries[] | select(.value.status == "hard-stop") | .key] | sort) as $stops
        | .graph.hard_stop = (if ($stops | length) == 0 then null
                              else {node_id:$stops[0],reason:"retry exhausted"} end)
      else .
      end
  '
}
