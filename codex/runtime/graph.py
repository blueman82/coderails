#!/usr/bin/env python3
"""Codex graph executor driven only by the checked-in execution graph contract."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import fcntl
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.dispatch import dispatch
from runtime.codex_exec import invoke as codex_exec

CONTRACT = Path(__file__).parents[2] / "skills/agentic-loop/execution-graph.md"
OUTCOMES = {"done", "skipped", "failed", "stale", "hard-stop"}
REQUIRED_GATES = ("review", "eval", "proof", "integrity", "wiki", "teardown")
GATE_RESULTS = {"review": ("review_status", "pass"), "eval": ("result", "GO"), "proof": ("result", "pass"), "integrity": ("integrity", "pass"), "wiki": ("result", "pass"), "teardown": ("result", "pass")}


class StateConflict(RuntimeError):
    """The state file advanced after this orchestrator loaded it."""


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
    edges: set[tuple[str, str]] = set()
    for record in records:
        targets = _expand(record["id"], unit_names)
        for prerequisite in record["prerequisites"]:
            sources = _expand(prerequisite, unit_names)
            for source in sources:
                for target in targets:
                    edges.add((source, target))
    for source, target in _diagram_edges(contract_path, declared):
        for expanded_source in _expand(source, unit_names):
            for expanded_target in _expand(target, unit_names):
                edges.add((expanded_source, expanded_target))
    edge_list = [{"from": source, "to": target} for source, target in sorted(edges)]
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
            _evidence(node, node["retry"]["attempts"], "skipped", "no work_units supplied; templated lane explicitly skipped")


def prepare_implementations(graph: dict[str, Any], config: Mapping[str, Any], *, catalog_root: Path | None = None) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Validate explicit node/gate mappings and attach gate identity to nodes."""
    if not isinstance(config, Mapping):
        return {}, ["implementation configuration must be an object"]
    node_records = config.get("nodes", {})
    gate_records = config.get("gates", {})
    if not isinstance(node_records, Mapping) or not isinstance(gate_records, Mapping):
        return {}, ["implementation configuration requires nodes and gates objects"]
    mappings = {str(name): dict(record) for name, record in node_records.items() if isinstance(record, Mapping)}
    errors: list[str] = []
    mode = config.get("mode", "live")
    seen: set[str] = set()
    for kind in REQUIRED_GATES:
        record = gate_records.get(kind)
        if not isinstance(record, Mapping):
            errors.append(f"missing gate implementation: {kind}")
            continue
        node = record.get("node")
        if not isinstance(node, str) or node not in graph["nodes"]:
            errors.append(f"gate {kind} references missing graph node")
            continue
        if node in seen:
            errors.append(f"multiple gates map to node: {node}")
            continue
        seen.add(node)
        mapping = dict(record)
        mapping["gate"] = kind
        mapping["mode"] = mode
        mapping["_run"] = config.get("run")
        if mode != "fixture":
            provenance = mapping.get("provenance")
            if not isinstance(provenance, Mapping) or provenance.get("provider") != "codex" or not isinstance(provenance.get("route"), str) or not provenance["route"].strip():
                errors.append(f"gate {kind} requires Codex provenance and route")
        mappings[node] = mapping
    if mode != "fixture":
        commands = [tuple(record.get("command", ())) for record in mappings.values() if record.get("gate")]
        if len(commands) == len(REQUIRED_GATES) and len(set(commands)) == 1:
            errors.append("live gate commands must be gate-specific")
    for name, node in graph["nodes"].items():
        if node.get("dispatch") and node.get("outcome") not in {"done", "skipped"} and name not in mappings:
            errors.append(f"missing implementation mapping: {name}")
    for name, record in mappings.items():
        error = _metadata_error(record, catalog_root=catalog_root)
        if error:
            errors.append(f"{name}: {error}")
    return mappings, errors


def gate_snapshot(graph: dict[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for kind, record in (config.get("gates", {}) if isinstance(config, Mapping) else {}).items():
        if isinstance(record, Mapping) and isinstance(record.get("node"), str):
            node = graph["nodes"].get(record["node"], {})
            result[kind] = {"node": record["node"], "outcome": node.get("outcome"), "evidence": node.get("evidence", [])}
    return result


def ready(graph: dict[str, Any], node: str) -> bool:
    nodes, edges, joins = graph["nodes"], graph["edges"], graph.get("joins", {})
    if node not in nodes or nodes[node].get("outcome") not in {"pending", "ready"}:
        return False
    predecessors = joins[node]["inputs"] if node in joins else [edge["from"] for edge in edges if edge["to"] == node]
    return all(item in nodes and nodes[item].get("outcome") in {"done", "skipped"} for item in predecessors)


def _test_callback_records(graph: dict[str, Any], handler: Callable[[str], str]) -> dict[str, Any]:
    return {
        name: {
            "provider": "codex", "skill_id": f"test.callback.{name}",
            "implementation_path": "codex/tests", "test_only": True,
            "outcome": (lambda name=name: handler(name)),
        }
        for name in graph["nodes"]
    }


def _metadata_error(record: Any, *, catalog_root: Path | None = None) -> str | None:
    if not isinstance(record, dict):
        return "implementation mapping must be an object"
    if record.get("provider") != "codex":
        return "provider must be codex"
    if not isinstance(record.get("skill_id"), str) or not record["skill_id"].strip():
        return "skill_id is required"
    if not isinstance(record.get("implementation_path"), str) or not record["implementation_path"].strip():
        return "implementation_path is required"
    if record.get("catalog_route") is not None:
        if catalog_root is None:
            return "catalog resolver root is required"
        try:
            package_catalog = catalog_root / "catalog.json"
            if package_catalog.is_file():
                catalog = json.loads(package_catalog.read_text(encoding="utf-8"))
                route = catalog.get("routes", {}).get(record.get("catalog_kind", "skills"), {}).get(str(record["catalog_route"]))
                if not isinstance(route, Mapping) or route.get("status") != "active":
                    raise ValueError("unknown or inactive package route")
                expected = str(route["path"])
                if not (catalog_root / expected).is_file():
                    raise ValueError("package route target is missing")
            else:
                catalog_dir = catalog_root / "codex"
                if str(catalog_dir) not in sys.path:
                    sys.path.insert(0, str(catalog_dir))
                from catalog import resolve  # type: ignore
                resolved = resolve(str(record["catalog_route"]), kind=record.get("catalog_kind"), root=catalog_root)
                expected = resolved.relative_to(catalog_root).as_posix()
            if expected != record["implementation_path"]:
                return f"catalog path mismatch: expected {expected}"
        except Exception as error:
            return f"catalog route unavailable: {error}"
    adapter = record.get("adapter")
    if adapter is not None and adapter != "codex-exec":
        return "adapter must be codex-exec"
    command = record.get("command")
    test_outcome = record.get("outcome")
    if command is not None and (not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command)):
        return "command must be a non-empty string array"
    if command is None and adapter != "codex-exec" and not (record.get("test_only") and test_outcome is not None):
        return "executable command is required"
    if adapter == "codex-exec" and (not isinstance(record.get("prompt"), str) or not record["prompt"].strip()):
        return "Codex exec prompt is required"
    if record.get("gate") and record.get("mode", "live") != "fixture":
        run = record.get("_run")
        provenance = record.get("provenance")
        if not isinstance(run, Mapping) or not all(isinstance(run.get(key), str) and run[key].strip() for key in ("run_id", "revision", "head")):
            return "live gate requires run_id, revision, and head context"
        if not isinstance(record.get("artifact_path"), str) or not record["artifact_path"].strip():
            return "live gate requires artifact_path"
        if not isinstance(provenance, Mapping) or provenance.get("provider") != "codex" or any(provenance.get(key) != run[key] for key in ("run_id", "revision", "head")):
            return "live gate provenance is not bound to the current run"
    return None


def _invoke(record: dict[str, Any], cwd: str | None) -> tuple[str, str]:
    live_gate = record.get("mode", "live") != "fixture" and (
        record.get("gate") in REQUIRED_GATES or record.get("gate") is not None or record.get("artifact_path") is not None
    )
    if record.get("outcome") is not None and not live_gate:
        value = record["outcome"]() if callable(record["outcome"]) else record["outcome"]
        return value, str(record.get("evidence", "configured test outcome"))
    execution_cwd = record.get("cwd", cwd)
    if record.get("adapter") == "codex-exec":
        outcome, output = codex_exec(record["prompt"], execution_cwd)
    else:
        outcome, output = dispatch(record["command"], execution_cwd)
    if outcome == "done" and record.get("gate") and record.get("mode", "live") != "fixture":
        kind = record["gate"]
        path = Path(record["artifact_path"])
        if not path.is_absolute():
            path = Path(record.get("cwd", cwd or Path.cwd())) / path
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
            field, expected = GATE_RESULTS[kind]
            run = record["_run"]
            if not isinstance(artifact, dict) or artifact.get("schema_version") != 1 or artifact.get("gate") != kind or artifact.get("provider") != "codex" or any(artifact.get(key) != run[key] for key in ("run_id", "revision", "head")) or artifact.get(field) != expected:
                return "failed", f"artifact validation failed for gate {kind}"
        except (OSError, ValueError, json.JSONDecodeError) as error:
            return "failed", f"artifact validation failed for gate {kind}: {error}"
        run = record["_run"]
        return "done", f"artifact validated gate={kind} provider=codex artifact_path={path} run_id={run['run_id']} revision={run['revision']} head={run['head']}"
    return outcome, output


def _evidence(node: dict[str, Any], attempt: int, outcome: str, output: str) -> None:
    node.setdefault("evidence", []).append({"attempt": attempt, "outcome": outcome, "output": output})
    node["retry"]["attempts"] = attempt


def _propagate_blocks(graph: dict[str, Any]) -> None:
    changed = True
    while changed:
        changed = False
        for name, node in graph["nodes"].items():
            if node.get("outcome") in {"done", "skipped", "hard-stop"}:
                continue
            predecessors = [edge["from"] for edge in graph["edges"] if edge["to"] == name]
            blocked = [item for item in predecessors if graph["nodes"].get(item, {}).get("outcome") in {"failed", "stale", "hard-stop"}]
            if blocked:
                node.update(status="hard-stop", outcome="hard-stop")
                _evidence(node, node["retry"]["attempts"], "hard-stop", f"blocked by hard-stop predecessor(s): {blocked}")
                changed = True


def execute(
    graph: dict[str, Any],
    implementations: Mapping[str, Any] | Callable[[str], str] | None = None,
    *,
    state_path: Path | None = None,
    persist: Callable[[dict[str, Any]], None] | None = None,
    cwd: str | None = None,
    expected_revision: int | None = None,
    catalog_root: Path | None = None,
) -> dict[str, Any]:
    """Dispatch complete ready waves and atomically persist after each wave."""
    if callable(implementations):
        implementations = _test_callback_records(graph, implementations)
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
                node.update(status="hard-stop", outcome="hard-stop")
                _evidence(node, node["retry"]["attempts"], "hard-stop", "blocked by unresolved predecessor or cycle")
            expected_revision = _persist(graph, state_path, persist, expected_revision)
            return graph
        results: list[tuple[str, str]] = []
        for name in wave:
            node = graph["nodes"][name]
            if not node.get("dispatch", True):
                node.update(status="skipped", outcome="skipped")
                _evidence(node, node["retry"]["attempts"], "skipped", "cross-cutting guard metadata; no standalone dispatch")
                results.append((name, "skipped"))
                continue
            record = implementations.get(name, node.get("implementation_record"))
            metadata = record if isinstance(record, dict) else {}
            node["provider"] = metadata.get("provider", "codex")
            node["skill_id"] = metadata.get("skill_id", "")
            node["implementation_path"] = metadata.get("implementation_path", "")
            error = "missing implementation mapping" if record is None else _metadata_error(record, catalog_root=catalog_root)
            if error:
                node.update(status="hard-stop", outcome="hard-stop")
                _evidence(node, node["retry"]["attempts"], "hard-stop", error)
                results.append((name, "hard-stop"))
                continue
            maximum = node["retry"].get("max", 5)
            attempts = node["retry"].get("attempts", 0)
            if not isinstance(maximum, int) or isinstance(maximum, bool) or not 0 <= maximum <= 5:
                raise ValueError(f"node {name} has invalid retry.max")
            outcome = "failed"
            while attempts < maximum:
                attempts += 1
                try:
                    outcome, output = _invoke(record, cwd)
                except Exception as error:  # external credentials/integrations fail closed here
                    outcome, output = "failed", f"dispatch error: {error}"
                if outcome not in OUTCOMES:
                    outcome, output = "failed", f"invalid implementation outcome: {outcome}"
                _evidence(node, attempts, outcome, output)
                if metadata.get("adapter") == "codex-exec":
                    node["evidence"][-1].update({"provider": "codex", "invocation": "codex exec", "mode": "live"})
                if outcome == "done" and metadata.get("gate") and metadata.get("mode") != "fixture":
                    path = Path(metadata["artifact_path"])
                    if not path.is_absolute():
                        path = Path(metadata.get("cwd", cwd or Path.cwd())) / path
                    run = metadata["_run"]
                    node["evidence"][-1].update({"gate": metadata["gate"], "provider": "codex", "artifact_path": str(path), "run_id": run["run_id"], "revision": run["revision"], "head": run["head"]})
                if outcome in {"done", "skipped", "hard-stop"}:
                    break
            if outcome in {"failed", "stale"}:
                outcome = "hard-stop"
                _evidence(node, attempts, "hard-stop", "retry limit exhausted")
            results.append((name, outcome))
        for name, outcome in results:
            graph["nodes"][name].update(status=outcome, outcome=outcome)
        _propagate_blocks(graph)
        expected_revision = _persist(graph, state_path, persist, expected_revision)


def _persist(graph: dict[str, Any], state_path: Path | None, persist: Callable[[dict[str, Any]], None] | None, expected_revision: int | None) -> int | None:
    if persist:
        persist(graph)
    if state_path:
        with _state_lock(state_path, exclusive=True):
            current = _read_unlocked(state_path).get("revision", 0) if state_path.exists() else 0
            if expected_revision is not None and current != expected_revision:
                raise StateConflict(f"state revision changed: expected {expected_revision}, found {current}")
            revision = current + 1
            graph["revision"] = revision
            _atomic_write(state_path, {"schema_version": 2, "status": "running", "provider": "codex", "revision": revision, "graph": graph})
            return revision
    return expected_revision


def _state_lock(path: Path, *, exclusive: bool):
    lock = open(str(path) + ".lock", "a+")
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    return lock


def _read_unlocked(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    with _state_lock(path, exclusive=False):
        return _read_unlocked(path)


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
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


def write_json(path: Path, value: dict[str, Any], *, expected_revision: int | None = None) -> None:
    with _state_lock(path, exclusive=True):
        current = _read_unlocked(path).get("revision", 0) if path.exists() else 0
        if expected_revision is not None and current != expected_revision:
            raise StateConflict(f"final state revision changed: expected {expected_revision}, found {current}")
        _atomic_write(path, value)
