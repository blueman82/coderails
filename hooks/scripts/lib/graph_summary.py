"""Read-only plain-language summaries of a Claude graph."""

from __future__ import annotations

from typing import Any, cast

from .graph_executor import graph_semantics


def budget_spent(node: dict[str, Any]) -> bool:
    """Report an exhausted respawn budget."""
    return bool(node["respawn"]["generation"] >= node["retry"]["max"])


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    """Plain-language status from graph state alone: done, active, ready, blocked and the human dependency."""
    graph = state["graph"]
    statuses = {node_id: node["status"] for node_id, node in graph["nodes"].items()}
    pending = sorted(n for n, s in statuses.items() if s not in {"done", "skipped"})
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
    if graph["hard_stop"] is not None:
        stopped = graph_semantics.describe_node(graph["hard_stop"]["node"])["display"]
        phase, detail = (
            "waiting for human",
            f"hard stop on {stopped}: {graph['hard_stop']['reason']}",
        )
    elif graph["active_wave"] is not None:
        phase, detail = "waiting for worker", f"wave {graph['active_wave']['wave_id']} dispatched"
        spent = [n for n in graph["active_wave"]["nodes"] if budget_spent(graph["nodes"][n])]
        if spent:
            detail += f"; recovery budget exhausted for {', '.join(spent)}: recover-wave will refuse, a human decides"
    elif ready:
        phase, detail = "ready to dispatch", "begin-wave then spawn the ready nodes"
    elif awaiting:
        phase = "waiting for human"
        detail = "; ".join(
            f"{row['node']} {row['status']}: run record-decision --worker-status-seq {row['seq']}" for row in awaiting
        )
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
