#!/usr/bin/env python3
"""Codex graph executor driven only by the checked-in execution graph contract."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import fcntl
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from runtime.contract import (
    CONTRACT,
    apply_work_unit_disposition,
    build_graph,
    codex_policy_mappings,
    load_contract,
    load_graph_policies,
)
from runtime.dispatch import dispatch
from runtime.parallel_review import PARALLEL_REVIEW_GATE, REVIEW_PROVIDERS, evaluate_parallel_review_join
from runtime.validation import _metadata_error, _test_callback_records
from runtime.codex_exec import invoke as codex_exec

CONTRACT = Path(__file__).parents[2] / "skills/agentic-loop/execution-graph.md"
OUTCOMES = {"done", "skipped", "failed", "stale", "hard-stop"}
REQUIRED_GATES = ("review", "eval", "proof", "integrity", "wiki", "teardown")
GATE_RESULTS = {"review": ("review_status", "pass"), "eval": ("result", "GO"), "proof": ("result", "pass"), "integrity": ("integrity", "pass"), "wiki": ("result", "pass"), "teardown": ("result", "pass")}


class StateConflict(RuntimeError):
    """The state file advanced after this orchestrator loaded it."""


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
        evaluated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    outcome = "done" if join["outcome"] == "pass" else join["outcome"]
    graph["nodes"][join_node].update(status=outcome, outcome=outcome, parallel_review=join)
    _evidence(graph["nodes"][join_node], graph["nodes"][join_node]["retry"]["attempts"], outcome, join.get("hard_stop_reason") or "unanimous approval")
    graph["parallel_review_join"] = join
    _persist(graph, state_path, persist=None, expected_revision=expected_revision, parallel_review=join)
    return join


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
    stop_before: set[str] | None = None,
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
        if stop_before and stop_before.intersection(wave):
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
