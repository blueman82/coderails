#!/bin/bash
# graph_readiness.sh — pure read-only readiness query for progress.json's
# durable execution graph (see skills/agentic-loop/loop-state.md's `graph`
# field docs and SKILL.md's "Execution graph" section).
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

result=$(jq --arg node "$node" '
  .graph as $g
  | ($g.nodes // {}) as $nodes
  | ($g.edges // []) as $edges
  | ($g.joins // {}) as $joins
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
