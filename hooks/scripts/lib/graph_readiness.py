#!/usr/bin/env python3
"""Pure read-only readiness query over progress.json's durable execution graph.

See skills/agentic-loop/loop-state.md's `graph` field docs and
skills/agentic-loop/execution-graph.md's node table.

Usage: graph_readiness.py <path-to-progress.json> <node-id>
Prints exactly "ready" or "blocked" to stdout (nothing else on stdout).
Exits 0 when ready, 1 when blocked -- including on any missing-arg,
missing-file, or unparseable-JSON case (fail-closed: a malformed graph is
not evidence of readiness, per loop-state.md's own instruction to treat
malformed graph entries as blocked).

READ-ONLY, by design: this script never writes progress.json (or any other
file). The orchestrator remains the sole writer of graph state, via
als_atomic_progress_update, once per wave after all dispatched nodes
return (see loop_state_common.sh). This script only answers the query
"is <node-id> ready right now, given the graph as currently recorded".

Readiness predicate: <node-id> is ready iff every edge {from,to:<node-id>}
in graph.edges has its `from` node's outcome in {done,skipped}
(terminal-success). If <node-id> is a join target listed in graph.joins
with mode:"all", that join's `inputs` list is used instead of raw edges --
ready iff every listed input's outcome is in {done,skipped}. A node with
no incoming edges and no matching join is vacuously ready.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

_STATUS_ENUM = {"pending", "ready", "running", "blocked", "done", "skipped", "failed", "hard-stop", "stale"}
_TERMINAL_SUCCESS = {"done", "skipped"}


class _InvalidError(Exception):
    """Raised internally when the progress document fails schema-v2 validation."""


def _is_num(value: object) -> bool:
    """Return True iff value is a JSON number (booleans do not count)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_str(value: object) -> bool:
    """Return True iff value is a JSON string."""
    return isinstance(value, str)


def _is_obj(value: object) -> bool:
    """Return True iff value is a JSON object."""
    return isinstance(value, dict)


def _is_arr(value: object) -> bool:
    """Return True iff value is a JSON array."""
    return isinstance(value, list)


def _validate_nodes(nodes: dict[str, Any]) -> None:
    """Raise _InvalidError unless every node value satisfies the schema-v2 node contract."""
    for value in nodes.values():
        if not _is_obj(value):
            raise _InvalidError
        status, outcome = value.get("status"), value.get("outcome")
        if status not in _STATUS_ENUM or outcome not in _STATUS_ENUM or status != outcome:
            raise _InvalidError
        if not _is_arr(value.get("evidence")):
            raise _InvalidError
        retry = value.get("retry")
        attempts: object = retry.get("attempts") if _is_obj(retry) else None
        max_attempts: object = retry.get("max") if _is_obj(retry) else None
        if not _is_num(attempts) or not _is_num(max_attempts):
            raise _InvalidError
        attempts = cast(float, attempts)
        max_attempts = cast(float, max_attempts)
        if attempts < 0 or max_attempts < 1 or max_attempts > 5 or attempts > max_attempts:
            raise _InvalidError


def _validate_edges(edges: list[Any], nodes: dict[str, Any]) -> None:
    """Raise _InvalidError unless every edge names two existing string node ids."""
    for edge in edges:
        if not _is_obj(edge):
            raise _InvalidError
        edge_from, edge_to = edge.get("from"), edge.get("to")
        if not _is_str(edge_from) or not _is_str(edge_to) or edge_from not in nodes or edge_to not in nodes:
            raise _InvalidError


def _validate_joins(joins: dict[str, Any], nodes: dict[str, Any]) -> None:
    """Raise _InvalidError unless every join satisfies the mode:"all" join contract."""
    for key, join in joins.items():
        if key not in nodes or not _is_obj(join) or join.get("mode") != "all":
            raise _InvalidError
        inputs = join.get("inputs")
        if not _is_arr(inputs) or not inputs:
            raise _InvalidError
        for item in inputs:
            if not _is_str(item) or item not in nodes:
                raise _InvalidError
        released_field = join.get("released")
        if released_field is not None and not isinstance(released_field, bool):
            raise _InvalidError
        released = released_field if isinstance(released_field, bool) else False
        if released != (nodes[key].get("status") == "done"):
            raise _InvalidError
        if released and not all(nodes[item].get("outcome") in _TERMINAL_SUCCESS for item in inputs):
            raise _InvalidError


def _tostring(revision: float) -> str:
    """Format an already-integer-valued revision the way jq's tostring renders it."""
    return str(int(revision))


def _validate_active_wave(active: object, nodes: dict[str, Any], revision: float) -> list[str]:
    """Raise _InvalidError unless active_wave (if present) satisfies its contract; return its node ids."""
    if active is None:
        return []
    if not _is_obj(active):
        raise _InvalidError
    active = cast(dict[str, Any], active)
    wave_id = active.get("wave_id")
    if not _is_str(wave_id) or wave_id != f"wave-{_tostring(revision)}":
        raise _InvalidError
    if active.get("revision") != revision:
        raise _InvalidError
    active_nodes = active.get("nodes")
    if not _is_arr(active_nodes) or not active_nodes:
        raise _InvalidError
    if len(set(active_nodes)) != len(active_nodes):
        raise _InvalidError
    for node_id in active_nodes:
        if not _is_str(node_id) or node_id not in nodes:
            raise _InvalidError
    return list(active_nodes)


def _has_cycle(edges: list[Any], joins: dict[str, Any], node_count: int) -> bool:
    """Return True iff the dependency graph (edges plus join inputs) contains a cycle."""
    pairs = {(edge["from"], edge["to"]) for edge in edges}
    for key, join in joins.items():
        pairs.update((item, key) for item in join["inputs"])
    for _ in range(node_count):
        new_pairs = {
            (left_from, right_to)
            for left_from, left_to in pairs
            for right_from, right_to in pairs
            if left_to == right_from
        }
        pairs |= new_pairs
    return any(pair_from == pair_to for pair_from, pair_to in pairs)


def _validate(data: object, node: str) -> None:
    """Raise _InvalidError unless data is a well-formed schema-v2 progress document naming node."""
    if not _is_obj(data):
        raise _InvalidError
    data = cast(dict[str, Any], data)
    if data.get("schema_version") != 2:
        raise _InvalidError
    if data.get("status") not in {"initialising", "in-progress", "complete"}:
        raise _InvalidError
    session_id, loop_id = data.get("session_id"), data.get("loop_id")
    if not _is_str(session_id) or not session_id or not _is_str(loop_id) or not loop_id:
        raise _InvalidError
    revision: object = data.get("revision")
    if not _is_num(revision):
        raise _InvalidError
    revision = cast(float, revision)
    if revision != int(revision) or revision <= 0:
        raise _InvalidError
    graph: object = data.get("graph")
    if not _is_obj(graph):
        raise _InvalidError
    graph = cast(dict[str, Any], graph)
    nodes: object = graph.get("nodes")
    edges: object = graph.get("edges")
    joins: object = graph.get("joins")
    if not _is_obj(nodes) or not _is_arr(edges) or not _is_obj(joins):
        raise _InvalidError
    nodes = cast(dict[str, Any], nodes)
    edges = cast(list[Any], edges)
    joins = cast(dict[str, Any], joins)
    if node not in nodes:
        raise _InvalidError
    _validate_nodes(nodes)
    _validate_edges(edges, nodes)
    _validate_joins(joins, nodes)
    hard_stop = graph.get("hard_stop")
    if hard_stop is not None and not _is_obj(hard_stop):
        raise _InvalidError
    active_node_ids = _validate_active_wave(graph.get("active_wave"), nodes, revision)
    running = sorted(key for key, value in nodes.items() if value.get("status") == "running")
    if running != sorted(active_node_ids):
        raise _InvalidError
    if _has_cycle(edges, joins, len(nodes)):
        raise _InvalidError


def _is_ready(graph: dict[str, Any], node: str) -> bool:
    """Return True iff node's status is pending/ready and every predecessor is terminal-success."""
    nodes, edges, joins = graph["nodes"], graph["edges"], graph["joins"]
    join = joins.get(node)
    if _is_obj(join) and join.get("mode") == "all":
        preds = join.get("inputs", [])
    else:
        preds = [edge["from"] for edge in edges if edge["to"] == node]
    if nodes[node].get("status", "pending") not in {"pending", "ready"}:
        return False
    return all(nodes[pred].get("outcome", "") in _TERMINAL_SUCCESS for pred in preds)


def main() -> int:
    """Print "ready"/"blocked" for argv[1]'s progress.json and argv[2]'s node id."""
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    node = sys.argv[2] if len(sys.argv) > 2 else ""
    if not path or not node or not Path(path).is_file():
        print("blocked")
        return 1
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        _validate(data, node)
        ready = _is_ready(data["graph"], node)
    except Exception:
        print("blocked")
        return 1
    if ready:
        print("ready")
        return 0
    print("blocked")
    return 1


if __name__ == "__main__":
    sys.exit(main())
