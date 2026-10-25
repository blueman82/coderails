"""Render a compact native graph status from the durable state."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_io import load
from graph_vocab import decision_pending


def budget_spent(node: dict[str, Any]) -> bool:
    """Report whether a node exhausted its respawn generation."""
    return bool(node["respawn"]["generation"] >= node["retry"]["max"])


def summarize(path: Path) -> dict[str, Any]:
    """Describe done, active, ready, blocked and human-dependent graph work."""
    state = load(path)
    graph = state["graph"]
    statuses = {node_id: node["status"] for node_id, node in graph["nodes"].items()}
    pending = sorted(n for n, status in statuses.items() if status not in {"done", "skipped"})
    ready = [] if graph["active_wave"] or graph["hard_stop"] else graph_semantics.ready(state)
    rows = state.get("worker_statuses")
    decisions = cast(list[object], rows) if isinstance(rows, list) else []
    awaiting: list[dict[str, Any]] = [
        cast(dict[str, Any], row)
        for row in decisions
        if isinstance(row, dict)
        and cast(dict[str, Any], row).get("decision_pending") is True
        and all(key in row for key in ("node", "status", "seq"))
    ]
    syncing = [
        cast(dict[str, Any], row)
        for row in decisions
        if isinstance(row, dict)
        and cast(dict[str, Any], row).get("decision_pending") is False
        and isinstance(cast(dict[str, Any], row).get("node"), str)
        and decision_pending(state, cast(str, cast(dict[str, Any], row)["node"]))
    ]
    if graph["hard_stop"] is not None:
        phase, detail = (
            "waiting for human",
            f"hard stop on {graph['hard_stop']['node']}: {graph['hard_stop']['reason']}",
        )
    elif graph["active_wave"] is not None:
        phase, detail = "waiting for worker", f"wave {graph['active_wave']['wave_id']} dispatched"
        spent = [node_id for node_id in graph["active_wave"]["nodes"] if budget_spent(graph["nodes"][node_id])]
        if spent:
            detail += f"; recovery budget exhausted for {', '.join(spent)}: recover-wave will refuse, a human decides"
    elif ready:
        phase, detail = "ready to dispatch", "begin-wave then spawn the ready nodes"
    elif awaiting:
        phase = "waiting for human"
        detail = "; ".join(
            f"{row['node']} {row['status']}: run record-decision --worker-status-seq {row['seq']}" for row in awaiting
        )
    elif syncing:
        phase, detail = "waiting for evidence", "decision sync pending: run flush-decisions after store reconciliation"
    elif not pending:
        phase, detail = "ready to complete", "run verify-completion"
    else:
        phase, detail = "waiting for evidence", "no node is ready; check pending dependencies"
    return {
        "phase": phase,
        "detail": detail,
        "node_names": graph_semantics.node_names(graph["nodes"]),
        "done": sorted(n for n in statuses if n not in pending),
        "active": list(graph["active_wave"]["nodes"]) if graph["active_wave"] else [],
        "ready": ready,
        "pending": pending,
    }
