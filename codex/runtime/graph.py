#!/usr/bin/env python3
"""Provider-neutral Codex graph executor driven by the canonical graph contract."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from runtime.dispatch import dispatch

CONTRACT = Path(__file__).parents[2] / "skills/agentic-loop/execution-graph.md"
OUTCOMES = {"done", "skipped", "failed", "stale", "hard-stop"}
NODE_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|")
REF_RE = re.compile(r"\b(?:S|U|J|G)-?[0-9]+(?:\.[0-9]+)?(?:[a-z])?(?:\[[^]]+\])?(?:-[a-z]+)?\b")


def load_contract(path: Path = CONTRACT) -> list[dict[str, Any]]:
    """Read node IDs and prerequisite references from execution-graph.md."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = NODE_RE.match(line)
        if match:
            node, prerequisites, ready_when = match.groups()
            records.append({"id": node, "prerequisites": REF_RE.findall(prerequisites), "ready_when": ready_when})
    if not records:
        raise ValueError(f"no graph nodes found in {path}")
    return records


PHASES = tuple(record["id"].removeprefix("S") for record in load_contract()) if CONTRACT.is_file() else ()


def node_id(phase: str) -> str:
    return f"S{phase}"


def _node(name: str) -> dict[str, Any]:
    return {"status": "pending", "outcome": "pending", "retry": {"attempts": 0, "max": 5}, "name": name}


def build_graph(
    phases: Iterable[str] | None = None,
    *,
    contract_path: Path = CONTRACT,
    joins: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, Any]:
    """Build graph state from the contract; ``phases`` exists only for small tests."""
    if phases is not None:
        phases = tuple(phases)
        exact = bool(joins) and any(name in phases for name in joins)
        ids = list(phases) if exact else [node_id(phase) for phase in phases]
        nodes = {name: _node(name) for name in ids}
        edges = [] if exact else [{"from": a, "to": b} for a, b in zip(ids, ids[1:])]
        join_map = {name: {"id": name, "mode": "all", "inputs": list(inputs)} for name, inputs in (joins or {}).items()}
        if exact and "P" in nodes:
            edges.extend({"from": "P", "to": item} for join in join_map.values() for item in join["inputs"] if item in nodes)
        for name, record in join_map.items():
            edges = [edge for edge in edges if edge["to"] != name]
            edges.extend({"from": item, "to": name} for item in record["inputs"])
            nodes.setdefault(name, _node(name))
        if {"S2", "S2.5", "S2.6", "S2.7a"}.issubset(nodes) and "J2" not in nodes:
            nodes["J2"] = _node("J2")
            join_map["J2"] = {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"]}
            edges = [edge for edge in edges if edge["to"] not in {"S2.5", "S2.6", "S2.7a"}]
            edges += [
                {"from": "S2", "to": "S2.5"}, {"from": "S2", "to": "S2.6"},
                {"from": "S2.5", "to": "J2"}, {"from": "S2.6", "to": "J2"},
                {"from": "J2", "to": "S2.7a"},
            ]
        return {"nodes": nodes, "edges": edges, "joins": join_map, "contract": "test graph"}

    records = load_contract(contract_path)
    nodes = {record["id"]: _node(record["id"]) for record in records}
    edges: list[dict[str, str]] = []
    join_map: dict[str, Any] = {}
    previous = None
    for record in records:
        name = record["id"]
        refs = [ref for ref in record["prerequisites"] if ref in nodes or ref.startswith(("J", "G"))]
        if not refs and previous:
            refs = [previous]
        for ref in refs:
            nodes.setdefault(ref, _node(ref))
            edges.append({"from": ref, "to": name})
        previous = name
    # The contract names J2 as the setup join and gives its two inputs in the diagram.
    if "J2" in {ref for edge in edges for ref in (edge["from"], edge["to"])} and "J2" not in join_map:
        inputs = [name for name in ("S2.5", "S2.6") if name in nodes]
        join_map["J2"] = {"id": "J2", "mode": "all", "inputs": inputs}
        nodes["J2"] = _node("J2")
        edges = [edge for edge in edges if edge["to"] != "J2"]
        edges.extend({"from": item, "to": "J2"} for item in inputs)
    return {"nodes": nodes, "edges": edges, "joins": join_map, "contract": str(contract_path)}


def ready(graph: dict[str, Any], node: str) -> bool:
    nodes, edges, joins = graph["nodes"], graph["edges"], graph.get("joins", {})
    if node not in nodes or nodes[node].get("outcome") not in {"pending", "ready"}:
        return False
    predecessors = joins[node]["inputs"] if joins.get(node, {}).get("mode") == "all" else [
        edge["from"] for edge in edges if edge["to"] == node
    ]
    return all(item in nodes and nodes[item].get("outcome") in {"done", "skipped"} for item in predecessors)


def _record_result(record: dict[str, Any], node: dict[str, Any], attempt: int, outcome: str, output: str) -> None:
    node.setdefault("evidence", []).append({"attempt": attempt, "outcome": outcome, "output": output})
    node["retry"]["attempts"] = attempt
    record["last_outcome"] = outcome


def _invoke(record: Any, cwd: str | None) -> tuple[str, str]:
    if callable(record):
        value = record()
        return value, "callable implementation"
    if isinstance(record, str):
        return record, "configured outcome"
    if not isinstance(record, dict):
        return "failed", "implementation record must be an object"
    if record.get("outcome") is not None:
        value = record["outcome"]() if callable(record["outcome"]) else record["outcome"]
        return value, str(record.get("evidence", "configured outcome"))
    command = record.get("command")
    if not isinstance(command, list):
        return "failed", "implementation record has no executable command"
    return dispatch(command, record.get("cwd", cwd))


def execute(
    graph: dict[str, Any],
    implementations: Mapping[str, Any] | None = None,
    *,
    state_path: Path | None = None,
    persist: Callable[[dict[str, Any]], None] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Run each ready wave, persist only after collecting the complete wave."""
    if callable(implementations):
        handler = implementations
        implementations = {name: (lambda name=name: handler(name)) for name in graph["nodes"]}
    implementations = implementations or {}
    terminal = {"done", "skipped", "hard-stop"}
    while True:
        remaining = [name for name, node in graph["nodes"].items() if node.get("outcome") not in terminal]
        if not remaining:
            return graph
        wave = sorted(name for name in remaining if ready(graph, name))
        if not wave:
            for name in remaining:
                node = graph["nodes"][name]
                node.setdefault("evidence", []).append({"attempt": node["retry"]["attempts"], "outcome": "hard-stop", "output": "blocked by failed or unresolved predecessor"})
            _persist(graph, state_path, persist)
            return graph
        results = []
        for name in wave:
            node = graph["nodes"][name]
            record = implementations.get(name, node.get("implementation_record"))
            metadata = record if isinstance(record, dict) else {}
            node["provider"] = metadata.get("provider", "codex")
            node["skill_id"] = metadata.get("skill_id", f"coderails.{name}")
            node["implementation_path"] = metadata.get("path", metadata.get("implementation_path", ""))
            maximum = node["retry"].get("max", 5)
            attempts = node["retry"].get("attempts", 0)
            if not isinstance(maximum, int) or isinstance(maximum, bool) or not 0 <= maximum <= 5:
                raise ValueError(f"node {name} has invalid retry.max")
            if record is None:
                _record_result(metadata, node, attempts, "hard-stop", "missing implementation record")
                results.append((name, "hard-stop"))
                continue
            outcome = "failed"
            while attempts < maximum:
                attempts += 1
                try:
                    outcome, output = _invoke(record, cwd)
                except Exception as error:  # an unavailable external gate is durable failure, never success
                    outcome, output = "failed", f"dispatch error: {error}"
                if outcome not in OUTCOMES:
                    outcome, output = "failed", f"invalid implementation outcome: {outcome}"
                _record_result(metadata, node, attempts, outcome, output)
                if outcome in {"done", "skipped", "hard-stop"}:
                    break
            if outcome in {"failed", "stale"}:
                outcome = "hard-stop"
                node.setdefault("evidence", []).append({"attempt": attempts, "outcome": outcome, "output": "retry limit exhausted"})
            results.append((name, outcome))
        for name, outcome in results:
            graph["nodes"][name].update(status=outcome, outcome=outcome)
        _persist(graph, state_path, persist)


def _persist(graph: dict[str, Any], state_path: Path | None, persist: Callable[[dict[str, Any]], None] | None) -> None:
    if persist:
        persist(graph)
    if state_path:
        write_json(state_path, {"schema_version": 2, "status": "running", "provider": "codex", "graph": graph})


def write_json(path: Path, value: dict[str, Any]) -> None:
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
