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
    return f"S{phase}" if phase not in {"-2", "-1"} else f"S{phase}"


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
    predecessors = joins[node]["inputs"] if joins.get(node, {}).get("mode") == "all" else [
        edge["from"] for edge in edges if edge["to"] == node
    ]
    return all(nodes.get(item, {}).get("outcome") in {"done", "skipped"} for item in predecessors)


def execute(graph: dict, handler: Callable[[str], str] | None = None) -> dict:
    """Run ready nodes in waves; handler returns ``done`` or ``skipped``."""
    handler = handler or (lambda _node: "done")
    remaining = set(graph["nodes"])
    while remaining:
        wave = sorted(node for node in remaining if ready(graph, node))
        if not wave:
            raise ValueError(f"graph is blocked or cyclic: {sorted(remaining)}")
        for node in wave:
            outcome = handler(node)
            if outcome not in {"done", "skipped"}:
                raise ValueError(f"phase {node} returned non-terminal outcome: {outcome}")
            graph["nodes"][node].update(status=outcome, outcome=outcome)
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

