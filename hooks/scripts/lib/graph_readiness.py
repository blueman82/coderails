#!/usr/bin/env python3
"""Print typed JSON {ready, reason_code} for one node using the installed current graph semantics."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_executor import graph_semantics, load
from hooks.scripts.lib.trace_row import append_row

READY, PENDING, UNKNOWN, UNREADABLE = "ready", "predecessor_pending", "node_unknown", "state_unreadable"
NOT_PENDING, GRAPH_BLOCKED, JOIN = "node_not_pending", "graph_blocked", "join_not_dispatchable"


def reason_for(state: dict[str, Any], node_id: str) -> str:
    """Return the closed readiness code for a node of a readable state."""
    graph = state["graph"]
    if node_id not in graph["nodes"]:
        return UNKNOWN
    if node_id in graph["joins"]:
        return JOIN
    if graph["nodes"][node_id]["status"] != "pending":
        return NOT_PENDING
    if graph["active_wave"] is not None or graph["hard_stop"] is not None:
        return GRAPH_BLOCKED
    return READY if node_id in graph_semantics.ready(state) else PENDING


def main(arguments: list[str] | None = None) -> int:
    """Print the typed verdict; exit 0 iff ready. Never changes durable state (trace rows are a separate file)."""
    arguments = sys.argv[1:] if arguments is None else arguments
    node_id = arguments[1] if len(arguments) == 2 else ""
    try:
        state = load(Path(arguments[0])) if arguments else {}
        code = reason_for(state, node_id) if state else UNREADABLE
    except ValueError:
        state, code = {}, UNREADABLE
    print(json.dumps({"ready": code == READY, "reason_code": code}))
    if code in {PENDING, UNKNOWN, NOT_PENDING, GRAPH_BLOCKED, JOIN}:
        append_row("graph_readiness", "not_ready", code, str(state.get("session_id") or ""), state.get("loop_id"))
    return 0 if code == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
