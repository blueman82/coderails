#!/usr/bin/env python3
"""Execute the durable coderails phase graph without a host-agent protocol."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

PHASES = (
    "-2", "-1", "0", "0.4", "0.5", "1", "2", "2.5", "2.6", "2.7a",
    "2.7b", "2.7c", "2.7d", "2.7e", "2.8", "3", "3a", "4", "4b", "5",
    "6", "7", "8", "9", "10", "11", "12", "13",
)


def node_id(phase: str) -> str:
    return f"S{phase}"


def build_graph(phases: Iterable[str] = PHASES) -> dict:
    """Return the documented graph shape, with setup forks joined explicitly."""
    phases = tuple(phases)
    ids = [node_id(phase) for phase in phases]
    nodes = {
        node: {"status": "pending", "outcome": "pending", "retry": {"attempts": 0, "max": 5}}
        for node in ids
    }
    edges = [{"from": a, "to": b} for a, b in zip(ids, ids[1:])]
    joins = {}
    if all(phase in phases for phase in ("2", "2.5", "2.6", "2.7a")):
        edges = [edge for edge in edges if edge["to"] not in {"S2.5", "S2.6", "S2.7a"}]
        edges += [
            {"from": "S2", "to": "S2.5"}, {"from": "S2", "to": "S2.6"},
            {"from": "S2.5", "to": "J2"}, {"from": "S2.6", "to": "J2"},
            {"from": "J2", "to": "S2.7a"},
        ]
        nodes["J2"] = {"status": "pending", "outcome": "pending", "retry": {"attempts": 0, "max": 5}}
        joins["J2"] = {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"]}
    return {"nodes": nodes, "edges": edges, "joins": joins}


def ready(graph: dict, node: str) -> bool:
    nodes, edges, joins = graph["nodes"], graph["edges"], graph.get("joins", {})
    if node not in nodes or nodes[node].get("status", nodes[node].get("outcome")) not in {"pending", "ready"}:
        return False
    predecessors = joins[node]["inputs"] if joins.get(node, {}).get("mode") == "all" else [
        edge["from"] for edge in edges if edge["to"] == node
    ]
    return bool(all(item in nodes for item in predecessors) and all(
        nodes[item].get("outcome") in {"done", "skipped"} for item in predecessors
    ))


def execute(graph: dict, handler: Callable[[str], str] | None = None) -> dict:
    """Run ready nodes in waves, collecting each wave before persisting it."""
    handler = handler or (lambda _node: "done")
    remaining = {
        node for node, value in graph["nodes"].items()
        if value.get("outcome") not in {"done", "skipped", "failed", "hard-stop"}
    }
    while remaining:
        wave = sorted(node for node in remaining if ready(graph, node))
        if not wave:
            raise ValueError(f"graph is blocked or cyclic: {sorted(remaining)}")
        results = []
        for node in wave:
            value = graph["nodes"][node]
            retry = value.get("retry", {})
            maximum = retry.get("max", 5)
            if not isinstance(maximum, int) or isinstance(maximum, bool) or not 0 <= maximum <= 5:
                raise ValueError(f"phase {node} has invalid retry.max")
            attempts = retry.get("attempts", 0)
            if not isinstance(attempts, int) or isinstance(attempts, bool) or not 0 <= attempts <= maximum:
                raise ValueError(f"phase {node} has invalid retry.attempts")
            outcome = "stale"
            candidate = "stale"
            while attempts < maximum:
                try:
                    candidate = handler(node)
                except Exception:
                    candidate = "failed"
                if candidate not in {"done", "skipped", "failed", "stale", "hard-stop"}:
                    raise ValueError(f"phase {node} returned invalid outcome: {candidate}")
                attempts += 1
                if candidate in {"done", "skipped", "hard-stop"}:
                    outcome = candidate
                    break
            if outcome == "stale" and candidate in {"failed", "stale"}:
                outcome = "hard-stop"
            results.append((node, outcome, attempts))
        for node, outcome, attempts in results:
            graph["nodes"][node].update(
                status=outcome, outcome=outcome, provider="codex",
                skill_id=f"coderails.phase-{node.removeprefix('S')}",
                implementation="codex/runtime/graph.py",
                retry={"attempts": attempts, "max": graph["nodes"][node]["retry"]["max"]},
            )
            remaining.remove(node)
    return graph


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
