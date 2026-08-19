#!/usr/bin/env python3
"""Parse and expand the checked-in execution graph contract."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


CONTRACT = Path(__file__).parents[2] / "skills/agentic-loop/execution-graph.md"


def _cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _code_spans(value: str) -> list[str]:
    return re.findall(r"`([^`]+)`", value)


def load_contract(path: Path = CONTRACT) -> list[dict[str, Any]]:
    """Parse the Markdown table without inventing IDs or prerequisite names."""
    lines = path.read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = []
    in_table = False
    for line in lines:
        cells = _cells(line)
        if not cells:
            if in_table:
                break
            continue
        if cells[0] == "ID":
            in_table = True
            continue
        if not in_table or not cells[0].startswith("`") or not cells[0].endswith("`"):
            continue
        node_id = cells[0][1:-1]
        prerequisites = cells[1] if len(cells) > 1 else ""
        conditional = cells[3] if len(cells) > 3 else ""
        records.append({
            "id": node_id,
            "prerequisites": _code_spans(prerequisites),
            "conditional": conditional,
            "dispatch": not any(marker in conditional.lower() for marker in ("no standalone work", "cross-cutting")),
        })
    if not records:
        raise ValueError(f"no graph contract table found in {path}")
    ids = {record["id"] for record in records}
    for record in records:
        unknown = [ref for ref in record["prerequisites"] if ref not in ids]
        if unknown:
            raise ValueError(f"{record['id']} references undeclared node(s): {unknown}")
    return records


def _diagram_edges(path: Path, ids: set[str]) -> list[tuple[str, str]]:
    """Read only exact declared IDs connected by arrows in the contract diagram."""
    edges: set[tuple[str, str]] = set()
    in_diagram = False
    token_re = re.compile("|".join(re.escape(item) for item in sorted(ids, key=len, reverse=True)))
    diagram: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```text"):
            in_diagram = True
            continue
        if in_diagram and line.strip() == "```":
            break
        if not in_diagram:
            continue
        diagram.append(line)
        found = list(token_re.finditer(line))
        for left, right in zip(found, found[1:]):
            if "->" in line[left.end():right.start()]:
                edges.add((left.group(), right.group()))
    for index, line in enumerate(diagram):
        if line.strip() != "v":
            continue
        prior = next((list(token_re.finditer(diagram[pos])) for pos in range(index - 1, max(-1, index - 4), -1) if token_re.search(diagram[pos])), [])
        following = next((list(token_re.finditer(diagram[pos])) for pos in range(index + 1, min(len(diagram), index + 4)) if token_re.search(diagram[pos])), [])
        if prior and following:
            source = min(prior, key=lambda match: abs(match.start() - line.find("v"))).group()
            target = min(following, key=lambda match: abs(match.start() - line.find("v"))).group()
            edges.add((source, target))
    return sorted(edges)


def _node(name: str) -> dict[str, Any]:
    return {"status": "pending", "outcome": "pending", "retry": {"attempts": 0, "max": 5}, "name": name, "dispatch": True}


def _expand(value: str, work_units: Sequence[str] | None) -> list[str]:
    if "[i]" not in value or not work_units:
        return [value]
    return [value.replace("[i]", f"[{unit}]") for unit in work_units]


def build_graph(
    phases: Iterable[str] | None = None,
    *,
    contract_path: Path = CONTRACT,
    joins: Mapping[str, Iterable[str]] | None = None,
    edges: Iterable[tuple[str, str]] | None = None,
    work_units: Sequence[str | Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build from the contract; ``phases``/``joins`` are test-only graph fixtures."""
    if phases is not None:
        names = tuple(phases)
        exact = bool(joins) and any(name in names for name in joins)
        ids = list(names) if exact else [f"S{name}" for name in names]
        nodes = {name: _node(name) for name in ids}
        edge_list = list(edges or ()) if exact else [(left, right) for left, right in zip(ids, ids[1:])]
        join_map = {name: {"id": name, "mode": "all", "inputs": list(inputs)} for name, inputs in (joins or {}).items()}
        for name, join in join_map.items():
            edge_list.extend((item, name) for item in join["inputs"])
            nodes.setdefault(name, _node(name))
        return {"nodes": nodes, "edges": [{"from": left, "to": right} for left, right in edge_list], "joins": join_map, "contract": "test graph"}

    if not contract_path.is_file():
        raise ValueError(f"contract_path does not exist: {contract_path}")
    records = load_contract(contract_path)
    unit_names = None
    if work_units is not None:
        unit_names = [str(unit.get("id", index)) if isinstance(unit, Mapping) else str(unit) for index, unit in enumerate(work_units)]
    declared = {record["id"] for record in records}
    node_names = [name for record in records for name in _expand(record["id"], unit_names)]
    dispatchable = {name: record["dispatch"] for record in records for name in _expand(record["id"], unit_names)}
    nodes = {name: dict(_node(name), dispatch=dispatchable[name]) for name in node_names}
    graph_edges: set[tuple[str, str]] = set()
    for record in records:
        targets = _expand(record["id"], unit_names)
        for prerequisite in record["prerequisites"]:
            sources = _expand(prerequisite, unit_names)
            for source in sources:
                for target in targets:
                    graph_edges.add((source, target))
    for source, target in _diagram_edges(contract_path, declared):
        for expanded_source in _expand(source, unit_names):
            for expanded_target in _expand(target, unit_names):
                graph_edges.add((expanded_source, expanded_target))
    edge_list = [{"from": source, "to": target} for source, target in sorted(graph_edges)]
    joins_map: dict[str, Any] = {}
    for name in nodes:
        inputs = [edge["from"] for edge in edge_list if edge["to"] == name]
        if len(inputs) > 1 or name.startswith("J"):
            joins_map[name] = {"id": name, "mode": "all", "inputs": inputs}
    return {"nodes": nodes, "edges": edge_list, "joins": joins_map, "contract": str(contract_path)}


def apply_work_unit_disposition(graph: dict[str, Any], work_units: Sequence[Any] | None) -> None:
    """Explicitly skip templated nodes when no work-unit list was supplied."""
    if work_units:
        return
    for name, node in graph["nodes"].items():
        if "[i]" in name and node.get("outcome") == "pending":
            node.update(status="skipped", outcome="skipped")
            node.setdefault("evidence", []).append({"attempt": node["retry"]["attempts"], "outcome": "skipped", "output": "no work_units supplied; templated lane explicitly skipped"})
