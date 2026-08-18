#!/usr/bin/env python3
"""Codex graph executor driven only by the checked-in execution graph contract."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import fcntl
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.dispatch import dispatch
from runtime.codex_exec import invoke as codex_exec

CONTRACT = Path(__file__).parents[2] / "skills/agentic-loop/execution-graph.md"
OUTCOMES = {"done", "skipped", "failed", "stale", "hard-stop"}
REQUIRED_GATES = ("review", "eval", "proof", "integrity", "wiki", "teardown")
GATE_RESULTS = {"review": ("review_status", "pass"), "eval": ("result", "GO"), "proof": ("result", "pass"), "integrity": ("integrity", "pass"), "wiki": ("result", "pass"), "teardown": ("result", "pass")}
PARALLEL_REVIEW_GATE = "parallel-review"
REVIEW_PROVIDERS = {"cl" + "aude", "codex"}


class StateConflict(RuntimeError):
    """The state file advanced after this orchestrator loaded it."""


def _cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _code_spans(value: str) -> list[str]:
    return re.findall(r"`([^`]+)`", value)


def _yaml_scalar(value: str) -> str:
    value = value.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def load_graph_policies(index_path: Path, *, repo_root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load the deliberately small graph_policies YAML subset fail-closed."""
    root = (repo_root or index_path.parent).resolve()
    lines = index_path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == "graph_policies:" and not line.startswith(" ")), None)
    if start is None:
        return {}
    policies: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    reviewer: dict[str, str] | None = None
    for line in lines[start + 1:]:
        if line and not line.startswith(" "):
            break
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        text = line.strip()
        if indent == 2 and text.endswith(":"):
            name = text[:-1]
            if not re.fullmatch(r"[A-Za-z0-9_.\[\]-]+", name) or name in policies:
                raise ValueError("invalid or duplicate graph policy id")
            current = policies[name] = {"node": name, "reviewers": []}
            reviewer = None
        elif current is not None and indent == 4 and text.endswith(":"):
            section = text[:-1]
            if section not in {"reviewers", "join", "frozen_input"}:
                raise ValueError(f"unknown graph policy section: {section}")
            current[section] = [] if section == "reviewers" else {}
        elif current is not None and indent == 6 and text.startswith("- "):
            if not isinstance(current.get("reviewers"), list):
                raise ValueError("reviewer entry outside reviewers section")
            reviewer = {}
            current["reviewers"].append(reviewer)
            key, value = text[2:].split(":", 1) if ":" in text[2:] else ("", "")
            if key != "provider":
                raise ValueError("reviewer must begin with provider")
            reviewer[key] = _yaml_scalar(value)
        elif current is not None and indent == 4 and ":" in text:
            key, value = text.split(":", 1)
            if key != "mode":
                raise ValueError(f"unknown graph policy field: {key}")
            current[key] = _yaml_scalar(value)
        elif current is not None and indent in {6, 8} and ":" in text:
            key, value = text.split(":", 1)
            value = _yaml_scalar(value)
            target: dict[str, Any] = reviewer if reviewer is not None and indent == 8 else current
            if indent == 6 and isinstance(current.get("join"), dict) and key in {"node", "policy"}:
                target = current["join"]
            elif indent == 6 and isinstance(current.get("frozen_input"), dict) and key == "digest_algorithm":
                target = current["frozen_input"]
            target[key] = value
    for node, policy in policies.items():
        if policy.get("mode", "parallel-review") != "parallel-review":
            raise ValueError(f"unsupported graph policy mode for {node}")
        reviewers = policy.get("reviewers")
        if not isinstance(reviewers, list) or {item.get("provider") for item in reviewers if isinstance(item, dict)} != REVIEW_PROVIDERS or len(reviewers) != 2:
            raise ValueError(f"graph policy {node} requires exactly the declared provider reviewers")
        for item in reviewers:
            route = item.get("route")
            if not isinstance(route, str) or not route or Path(route).is_absolute():
                raise ValueError(f"invalid reviewer route for {node}")
            resolved = (root / route).resolve()
            if root not in resolved.parents or not resolved.is_file():
                raise ValueError(f"reviewer route escapes repo or is missing for {node}")
        join = policy.get("join")
        frozen = policy.get("frozen_input")
        if not isinstance(join, dict) or join.get("node") != f"J{node}[i]" and join.get("node") != "J4b-review":
            raise ValueError(f"graph policy {node} has invalid join node")
        if join.get("policy") != "unanimous" or not isinstance(frozen, dict) or frozen.get("digest_algorithm") != "sha256":
            raise ValueError(f"graph policy {node} has invalid join or digest policy")
    return policies


def codex_policy_mappings(graph: Mapping[str, Any], policies: Mapping[str, Any], *, repo_root: Path) -> dict[str, dict[str, Any]]:
    """Build only the Codex-side mappings; the other provider remains owner-controlled."""
    mappings: dict[str, dict[str, Any]] = {}
    for node, policy in policies.items():
        reviewer = next((item for item in policy.get("reviewers", []) if item.get("provider") == "codex"), None)
        if not isinstance(reviewer, Mapping):
            raise ValueError(f"missing Codex reviewer mapping for {node}")
        route = str(reviewer.get("route", ""))
        resolved = (repo_root / route).resolve()
        if not route.startswith("codex/") or repo_root.resolve() not in resolved.parents or not resolved.is_file():
            raise ValueError(f"invalid Codex reviewer route for {node}")
        reviewer_node = f"{node}-codex[i]"
        if reviewer_node not in graph.get("nodes", {}):
            raise ValueError(f"Codex reviewer node is not in graph: {reviewer_node}")
        mappings[reviewer_node] = {
            "provider": "codex",
            "skill_id": Path(route).parent.name,
            "implementation_path": route,
            "adapter": "codex-exec",
            "prompt": f"Run the Codex parallel-review route for {node} against the frozen input.",
            "policy_node": node,
        }
    return mappings


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
        commands = [tuple(record.get("command", ())) if record.get("adapter") != "codex-exec" else record.get("prompt", "") for record in mappings.values() if record.get("gate")]
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


def _parallel_review_input(value: Mapping[str, Any] | Path) -> Mapping[str, Any] | None:
    if isinstance(value, Path):
        try:
            value = json.loads(value.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
    return value if isinstance(value, Mapping) else None


def _parallel_review_input_digest(record: Mapping[str, Any] | None) -> str | None:
    if not record:
        return None
    return record.get("digest") or record.get("frozen_input_digest")


def _valid_parallel_review_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def evaluate_parallel_review_join(
    canonical_input: Mapping[str, Any] | Path,
    reviewer_records: Mapping[str, Mapping[str, Any] | Path | None],
    *,
    reviewer_outcomes: Mapping[str, str] | None = None,
    expected_run: Mapping[str, str] | None = None,
    node: str = "J4b-review[i]",
    evaluated_by: str = "neutral-join",
    evaluated_at: str = "",
) -> dict[str, Any]:
    """Validate independent review evidence and return the durable join record.

    This is deliberately pure: the neutral caller owns persistence, while each
    provider owns only its own evidence file. A skipped pair is an intentional
    non-review; every asymmetric or invalid pair is a hard-stop.
    """
    canonical = _parallel_review_input(canonical_input)
    providers = tuple(sorted(set((reviewer_outcomes or {}).keys()) | set(reviewer_records.keys())))
    outcomes = reviewer_outcomes or {provider: "done" for provider in providers}
    inputs: dict[str, Any] = {}
    base = {
        "schema_version": 1,
        "node": node,
        "policy": "unanimous",
        "frozen_input_digest": _parallel_review_input_digest(canonical),
        "inputs": inputs,
        "outcome": "hard-stop",
        "hard_stop_reason": None,
        "evaluated_at": evaluated_at,
        "evaluated_by": evaluated_by,
    }
    if set(providers) != REVIEW_PROVIDERS:
        base["hard_stop_reason"] = "missing-evidence"
        return base
    if all(outcomes.get(provider) == "skipped" for provider in providers):
        base["outcome"] = "skipped"
        return base
    if canonical is None or not _parallel_review_input_digest(canonical):
        base["hard_stop_reason"] = "missing-evidence"
        return base

    canonical_digest = _parallel_review_input_digest(canonical)
    for provider in providers:
        record = _parallel_review_input(reviewer_records.get(provider))
        inputs[provider] = {
            "run_id": record.get("run_id") if record else None,
            "revision": record.get("revision") if record else None,
            "head": record.get("head") if record else None,
            "outcome": record.get("verdict", {}).get("outcome") if record else None,
            "verdict_ref": str(reviewer_records.get(provider)) if isinstance(reviewer_records.get(provider), Path) else None,
        }
        if outcomes.get(provider) == "skipped" or record is None:
            base["hard_stop_reason"] = "missing-evidence"
            return base
        required_fields = ("run_id", "revision", "head", "frozen_input_digest")
        if (
            record.get("schema_version") != 1
            or record.get("gate") != PARALLEL_REVIEW_GATE
            or record.get("provider") != provider
            or record.get("digest_algorithm") != "sha256"
            or any(not isinstance(record.get(field), str) or not record[field].strip() for field in required_fields)
            or not _valid_parallel_review_timestamp(record.get("written_at"))
        ):
            base["hard_stop_reason"] = "mismatched-evidence"
            return base
        if expected_run and any(record.get(key) != expected_run.get(key) for key in ("run_id", "revision", "head")):
            base["hard_stop_reason"] = "stale-evidence"
            return base
        if record.get("frozen_input_digest") != canonical_digest:
            base["hard_stop_reason"] = "mismatched-evidence"
            return base
        verdict = record.get("verdict")
        if not isinstance(verdict, Mapping) or verdict.get("outcome") not in {"approve", "reject"} or not str(verdict.get("reasoning", "")).strip():
            base["hard_stop_reason"] = "conflicting-verdicts"
            return base

    if all(inputs[provider]["outcome"] == "approve" for provider in providers):
        base["outcome"] = "pass"
    else:
        base["hard_stop_reason"] = "conflicting-verdicts"
    return base


def persist_parallel_review_join(
    graph: dict[str, Any],
    policy: Mapping[str, Any],
    canonical_input: Mapping[str, Any] | Path,
    reviewer_records: Mapping[str, Mapping[str, Any] | Path | None],
    *,
    expected_run: Mapping[str, str],
    state_path: Path,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Evaluate and atomically persist the neutral join plus graph state."""
    join_node = str(policy.get("join", {}).get("node", ""))
    if join_node not in graph.get("nodes", {}) and f"{join_node}[i]" in graph.get("nodes", {}):
        join_node = f"{join_node}[i]"
    if join_node not in graph.get("nodes", {}):
        raise ValueError(f"parallel-review join node is not in graph: {join_node}")
    join = evaluate_parallel_review_join(
        canonical_input,
        reviewer_records,
        expected_run=expected_run,
        node=join_node,
    )
    outcome = "done" if join["outcome"] == "pass" else join["outcome"]
    graph["nodes"][join_node].update(status=outcome, outcome=outcome, parallel_review=join)
    _evidence(graph["nodes"][join_node], graph["nodes"][join_node]["retry"]["attempts"], outcome, join.get("hard_stop_reason") or "unanimous approval")
    graph["parallel_review_join"] = join
    _persist(graph, state_path, persist=None, expected_revision=expected_revision, parallel_review=join)
    return join


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
        if record.get("gate") == PARALLEL_REVIEW_GATE and not isinstance(record.get("frozen_input_digest"), str):
            return "parallel-review gate requires frozen_input_digest"
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
            run = record["_run"]
            valid = isinstance(artifact, dict) and artifact.get("schema_version") == 1 and artifact.get("gate") == kind and artifact.get("provider") == "codex" and all(artifact.get(key) == run[key] for key in ("run_id", "revision", "head"))
            if kind == PARALLEL_REVIEW_GATE:
                verdict = artifact.get("verdict") if isinstance(artifact, dict) else None
                valid = valid and artifact.get("frozen_input_digest") == record.get("frozen_input_digest") and isinstance(verdict, dict) and verdict.get("outcome") in {"approve", "reject"} and str(verdict.get("reasoning", "")).strip()
            else:
                field, expected = GATE_RESULTS[kind]
                valid = valid and artifact.get(field) == expected
            if not valid:
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


def _run_node(name: str, node: dict[str, Any], record: Any, cwd: str | None, catalog_root: Path | None) -> tuple[str, dict[str, Any], str]:
    """Execute one ready node without touching shared graph state."""
    metadata = record if isinstance(record, dict) else {}
    result = {"provider": metadata.get("provider", "codex"), "skill_id": metadata.get("skill_id", ""), "implementation_path": metadata.get("implementation_path", "")}
    error = "missing implementation mapping" if record is None else _metadata_error(record, catalog_root=catalog_root)
    if error:
        return name, {"status": "hard-stop", "outcome": "hard-stop", "evidence": [{"attempt": node["retry"]["attempts"], "outcome": "hard-stop", "output": error}]}, "hard-stop"
    maximum = node["retry"].get("max", 5)
    attempts = node["retry"].get("attempts", 0)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or not 0 <= maximum <= 5:
        raise ValueError(f"node {name} has invalid retry.max")
    evidence = []
    outcome = "failed"
    while attempts < maximum:
        attempts += 1
        try:
            outcome, output = _invoke(record, cwd)
        except Exception as error:  # external credentials/integrations fail closed here
            outcome, output = "failed", f"dispatch error: {error}"
        if outcome not in OUTCOMES:
            outcome, output = "failed", f"invalid implementation outcome: {outcome}"
        entry = {"attempt": attempts, "outcome": outcome, "output": output}
        if metadata.get("adapter") == "codex-exec":
            entry.update({"provider": "codex", "invocation": "codex exec", "mode": "live"})
        if outcome == "done" and metadata.get("gate") and metadata.get("mode") != "fixture":
            path = Path(metadata["artifact_path"])
            if not path.is_absolute():
                path = Path(metadata.get("cwd", cwd or Path.cwd())) / path
            run = metadata["_run"]
            entry.update({"gate": metadata["gate"], "provider": "codex", "artifact_path": str(path), "run_id": run["run_id"], "revision": run["revision"], "head": run["head"]})
        evidence.append(entry)
        if outcome in {"done", "skipped", "hard-stop"}:
            break
    if outcome in {"failed", "stale"}:
        outcome = "hard-stop"
        evidence.append({"attempt": attempts, "outcome": "hard-stop", "output": "retry limit exhausted"})
    result.update({"status": outcome, "outcome": outcome, "evidence": evidence, "retry": {"attempts": attempts, "max": maximum}})
    return name, result, outcome


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
        runnable = [name for name in wave if graph["nodes"][name].get("dispatch", True)]
        results = []
        with ThreadPoolExecutor(max_workers=max(1, len(runnable))) as pool:
            futures = [pool.submit(_run_node, name, graph["nodes"][name], implementations.get(name, graph["nodes"][name].get("implementation_record")), cwd, catalog_root) for name in runnable]
            for future in futures:
                results.append(future.result())
        for name in wave:
            if not graph["nodes"][name].get("dispatch", True):
                graph["nodes"][name].update(status="skipped", outcome="skipped")
                _evidence(graph["nodes"][name], graph["nodes"][name]["retry"]["attempts"], "skipped", "cross-cutting guard metadata; no standalone dispatch")
            else:
                _, update, _ = next(item for item in results if item[0] == name)
                graph["nodes"][name].update(update)
        _propagate_blocks(graph)
        expected_revision = _persist(graph, state_path, persist, expected_revision)


def _persist(graph: dict[str, Any], state_path: Path | None, persist: Callable[[dict[str, Any]], None] | None, expected_revision: int | None, parallel_review: Mapping[str, Any] | None = None) -> int | None:
    if persist:
        persist(graph)
    if state_path:
        with _state_lock(state_path, exclusive=True):
            current = _read_unlocked(state_path).get("revision", 0) if state_path.exists() else 0
            if expected_revision is not None and current != expected_revision:
                raise StateConflict(f"state revision changed: expected {expected_revision}, found {current}")
            revision = current + 1
            graph["revision"] = revision
            state = {"schema_version": 2, "status": "running", "provider": "codex", "revision": revision, "graph": graph}
            join = parallel_review or graph.get("parallel_review_join")
            if isinstance(join, Mapping):
                state["parallel_review_join"] = dict(join)
            _atomic_write(state_path, state)
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
