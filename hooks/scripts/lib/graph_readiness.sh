#!/bin/bash
# graph_readiness.sh — pure read-only readiness query for progress.json's
# durable execution graph (see skills/agentic-loop/loop-state.md's `graph`
# field docs and skills/agentic-loop/execution-graph.md's node table).
#
# Usage: graph_readiness.sh <path-to-progress.json> <node-id>
# Prints exactly "ready" or "blocked" to stdout (nothing else on stdout).
# Exits 0 when ready, 1 when blocked — including on any missing-arg,
# missing-file, or unparseable-JSON case (fail-closed: a malformed graph is
# not evidence of readiness, per loop-state.md's own instruction to treat
# malformed graph entries as blocked).
#
# READ-ONLY, by design: this script never writes progress.json (or any other
# file). The orchestrator remains the sole writer of graph state, via
# als_atomic_progress_update, once per wave after all dispatched nodes
# return (see loop_state_common.sh). This script only answers the query
# "is <node-id> ready right now, given the graph as currently recorded".
#
# Readiness predicate: <node-id> is ready iff every edge {from,to:<node-id>}
# in graph.edges has its `from` node's outcome in {done,skipped}
# (terminal-success). If <node-id> is a join target listed in graph.joins
# with mode:"all", that join's `inputs` list is used instead of raw edges —
# ready iff every listed input's outcome is in {done,skipped}. A node with
# no incoming edges and no matching join is vacuously ready.

set -u

path="${1:-}"
node="${2:-}"

if [ -z "$path" ] || [ -z "$node" ] || [ ! -f "$path" ]; then
    echo "blocked"
    exit 1
fi

result=$(jq -e --arg node "$node" '
  .graph as $g
  | ($g.nodes) as $nodes
  | ($g.edges) as $edges
  | ($g.joins) as $joins
  | ($g.active_wave) as $active
  | ($g.hard_stop) as $hard_stop
  | ($edges + [$joins | to_entries[] as $join
                | $join.value.inputs[]? | {from:.,to:$join.key}]) as $dependencies
  | if ((.session_id | type) != "string" or (.session_id | length) == 0
        or (.loop_id | type) != "string" or (.loop_id | length) == 0
        or (.revision | type) != "number" or (.revision | floor) != .revision or .revision <= 0
        or ($g | type) != "object"
        or ($nodes | type) != "object"
        or ($edges | type) != "array"
        or ($joins | type) != "object"
        or ($nodes | has($node) | not)
        or ([$nodes | to_entries[]
              | select((.value | type) != "object"
                       or (.value.status | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
                       or (.value.outcome | IN("pending","ready","running","blocked","done","skipped","failed","hard-stop","stale") | not)
                       or .value.status != .value.outcome
                       or (.value.retry.attempts | type) != "number"
                       or (.value.retry.max | type) != "number"
                       or .value.retry.attempts < 0
                       or .value.retry.max < 1
                       or .value.retry.max > 5
                       or .value.retry.attempts > .value.retry.max)] | length) != 0
        or ([$edges[] as $edge
              | select(($edge | type) != "object"
                       or ($edge.from | type) != "string"
                       or ($edge.to | type) != "string"
                       or ($nodes | has($edge.from) | not)
                       or ($nodes | has($edge.to) | not))] | length) != 0
        or ([$joins | to_entries[] as $join
              | select(($nodes | has($join.key) | not)
                       or ($join.value | type) != "object"
                       or $join.value.mode != "all"
                       or ($join.value.inputs | type) != "array"
                       or ($join.value.inputs | length) == 0
                       or ([$join.value.inputs[] as $input
                            | select(($input | type) != "string" or ($nodes | has($input) | not))] | length) != 0
                       or (($join.value | has("released")) and ($join.value.released | type) != "boolean")
                       or (($join.value.released // false) != ($nodes[$join.key].status == "done"))
                       or (($join.value.released // false)
                           and ($join.value.inputs | all(. as $input
                               | ($nodes[$input].outcome // "") | IN("done","skipped")) | not)))] | length) != 0
        or ($hard_stop != null and (($hard_stop | type) != "object"))
        or (($active != null)
            and (($active | type) != "object"
                 or ($active.wave_id | type) != "string"
                 or $active.wave_id != ("wave-" + (.revision | tostring))
                 or $active.revision != .revision
                 or ($active.nodes | type) != "array"
                 or ($active.nodes | length) == 0
                 or ($active.nodes | unique | length) != ($active.nodes | length)
                 or ([$active.nodes[] as $id
                      | select(($id | type) != "string" or ($nodes | has($id) | not))] | length) != 0))
        or (([$nodes | to_entries[] | select(.value.status == "running") | .key] | sort)
            != (if $active == null then [] else ($active.nodes | sort) end))
        or ((reduce range(0; ($nodes | length)) as $i ($dependencies;
               . + [.[] as $left
                    | .[] as $right
                    | select($left.to == $right.from)
                    | {from:$left.from,to:$right.to}]
               | unique_by([.from,.to])))
            | any(.from == .to)))
    then error("invalid graph")
    else .
    end
  | (if (($joins[$node] // null) != null) and ($joins[$node].mode == "all")
     then ($joins[$node].inputs // [])
     else ($edges | map(select(.to == $node) | .from))
     end) as $preds
  | (($nodes[$node].status // "pending") | IN("pending","ready"))
    and ($preds | all($nodes[.].outcome // "" | IN("done","skipped")))
' "$path" 2>/dev/null)
rc=$?

if [ "$rc" -eq 0 ] && [ "$result" = "true" ]; then
    echo "ready"
    exit 0
else
    echo "blocked"
    exit 1
fi
