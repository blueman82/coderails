#!/usr/bin/env python3
"""Small durable graph executor with bounded retries and explicit joins."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

TERMINAL = {"done", "skipped"}
OUTCOMES = TERMINAL | {"failed", "stale", "hard-stop"}


def build_graph(nodes: Iterable[str], edges: Iterable[tuple[str, str]] = ()) -> dict:
    names = tuple(nodes)
    return {
        "nodes": {
            name: {"status": "pending", "outcome": "pending", "retry": {"attempts": 0, "max": 5}}
            for name in names
        },
        "edges": [{"from": left, "to": right} for left, right in edges],
        "joins": {},
    }


def ready(graph: dict, node: str) -> bool:
    value = graph["nodes"].get(node, {})
    if value.get("outcome") not in {"pending", "ready"}:
        return False
    join = graph.get("joins", {}).get(node)
    predecessors = join["inputs"] if join and join.get("mode") == "all" else [
        edge["from"] for edge in graph.get("edges", []) if edge["to"] == node
    ]
    return all(graph["nodes"].get(item, {}).get("outcome") in TERMINAL for item in predecessors)


def execute(graph: dict, handler: Callable[[str], str]) -> dict:
    remaining = {name for name, value in graph["nodes"].items() if value.get("outcome") not in OUTCOMES}
    while remaining:
        wave = sorted(name for name in remaining if ready(graph, name))
        if not wave:
            raise ValueError(f"graph is blocked or cyclic: {sorted(remaining)}")
        results = []
        for name in wave:
            node = graph["nodes"][name]
            retry = node.setdefault("retry", {})
            maximum = retry.get("max", 5)
            attempts = retry.get("attempts", 0)
            if isinstance(maximum, bool) or not isinstance(maximum, int) or not 0 <= maximum <= 5:
                raise ValueError(f"{name}: retry.max must be 0..5")
            if isinstance(attempts, bool) or not isinstance(attempts, int) or not 0 <= attempts <= maximum:
                raise ValueError(f"{name}: retry.attempts is invalid")
            outcome = "stale"
            while attempts < maximum:
                try:
                    candidate = handler(name)
                except Exception:
                    candidate = "failed"
                if candidate not in OUTCOMES:
                    raise ValueError(f"{name}: invalid outcome {candidate!r}")
                attempts += 1
                if candidate in TERMINAL | {"hard-stop"}:
                    outcome = candidate
                    break
                outcome = candidate
            if outcome in {"failed", "stale"}:
                outcome = "hard-stop"
            results.append((name, outcome, attempts, maximum))
        for name, outcome, attempts, maximum in results:
            graph["nodes"][name].update(
                status=outcome, outcome=outcome, provider="codex",
                retry={"attempts": attempts, "max": maximum},
            )
            remaining.remove(name)
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
