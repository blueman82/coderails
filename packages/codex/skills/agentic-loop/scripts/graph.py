#!/usr/bin/env python3
"""Operate the filesystem-backed native Codex agentic-loop graph."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, cast

from graph_evidence import (
    bind_worker_evidence,
    has_current_wave_dispatch,
    transcript_cursor,
    validate_completion_evidence,
    validate_evals,
    validate_worker_evidence,
)
from graph_identity import GraphError, active_nodes, classify_worker_evidence, task_name, task_node
from json_types import JsonValue

STATUSES = {"pending", "ready", "running", "blocked", "done", "skipped", "failed", "hard-stop", "stale"}
SUCCESS = {"done", "skipped"}


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GraphError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _array(value: object, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise GraphError(f"{label} must be an array")
    return cast(list[JsonValue], value)


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphError(f"{label} must be a non-empty string")
    return value


def _validate_cancelled_waves(graph: dict[str, Any]) -> None:
    cancelled_waves = _array(graph.get("cancelled_waves", []), "graph.cancelled_waves")
    cancelled_ids: set[str] = set()
    for index, raw_cancelled in enumerate(cancelled_waves):
        cancelled = _object(raw_cancelled, f"graph.cancelled_waves[{index}]")
        if set(cancelled) != {"id", "revision"}:
            raise GraphError("cancelled wave must contain exactly id and revision")
        wave_id = _nonempty(cancelled.get("id"), f"graph.cancelled_waves[{index}].id")
        wave_revision = cancelled.get("revision")
        if (
            isinstance(wave_revision, bool)
            or not isinstance(wave_revision, int)
            or wave_revision < 1
            or wave_id != f"wave-{wave_revision}"
            or wave_id in cancelled_ids
        ):
            raise GraphError("cancelled wave is invalid or duplicated")
        cancelled_ids.add(wave_id)


def _validate_state(state: object) -> dict[str, Any]:
    root = _object(state, "state")
    if root.get("schema_version") != 2:
        raise GraphError("schema_version must be 2")
    _nonempty(root.get("session_id"), "session_id")
    _nonempty(root.get("loop_id"), "loop_id")
    if root.get("status") not in {"initialising", "in-progress", "complete"}:
        raise GraphError("state has invalid status")
    revision = root.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise GraphError("revision must be a non-negative integer")
    graph = _object(root.get("graph"), "graph")
    nodes = _object(graph.get("nodes"), "graph.nodes")
    if not nodes:
        raise GraphError("graph.nodes must not be empty")
    for node_id, raw_node in nodes.items():
        _nonempty(node_id, "node id")
        node = _object(raw_node, f"node {node_id}")
        if node.get("status") not in STATUSES:
            raise GraphError(f"node {node_id} has invalid status")
        if node.get("outcome") != node["status"]:
            raise GraphError(f"node {node_id} status and outcome disagree")
        retry = _object(node.get("retry"), f"node {node_id}.retry")
        attempts, maximum = retry.get("attempts"), retry.get("max")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (attempts, maximum)):
            raise GraphError(f"node {node_id} retry counts must be integers")
        attempts, maximum = cast(int, attempts), cast(int, maximum)
        if attempts < 0 or not 1 <= maximum <= 5 or attempts > maximum:
            raise GraphError(f"node {node_id} has invalid retry bounds")
        if not isinstance(node.get("evidence"), list):
            raise GraphError(f"node {node_id}.evidence must be an array")
    edges = _array(graph.get("edges"), "graph.edges")
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for index, raw_edge in enumerate(edges):
        edge = _object(raw_edge, f"edge {index}")
        source = _nonempty(edge.get("from"), f"edge {index}.from")
        target = _nonempty(edge.get("to"), f"edge {index}.to")
        if source not in nodes or target not in nodes or source == target:
            raise GraphError(f"edge {index} references an unknown or identical node")
        dependencies[target].add(source)
    joins = _object(graph.get("joins"), "graph.joins")
    for join_id, raw_join in joins.items():
        if join_id not in nodes:
            raise GraphError(f"join {join_id} references an unknown node")
        join = _object(raw_join, f"join {join_id}")
        if join.get("mode") != "all" or not isinstance(join.get("released"), bool):
            raise GraphError(f"join {join_id} must be an all-input join")
        inputs = _array(join.get("inputs"), f"join {join_id}.inputs")
        if not inputs or any(not isinstance(item, str) for item in inputs):
            raise GraphError(f"join {join_id}.inputs must be a non-empty unique array")
        input_nodes = cast(list[str], inputs)
        if len(input_nodes) != len(set(input_nodes)):
            raise GraphError(f"join {join_id}.inputs must be a non-empty unique array")
        if any(item not in nodes or item == join_id for item in input_nodes):
            raise GraphError(f"join {join_id} references an unknown or identical input")
        dependencies[join_id].update(input_nodes)
        released = join["released"]
        if released != (nodes[join_id]["status"] == "done"):
            raise GraphError(f"join {join_id} release state disagrees with its node")
        if released and not all(nodes[node_id]["status"] in SUCCESS for node_id in input_nodes):
            raise GraphError(f"join {join_id} released before every input succeeded")
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    indegree = {node_id: len(required) for node_id, required in dependencies.items()}
    for target, required in dependencies.items():
        for source in required:
            outgoing[source].add(target)
    queue = deque(sorted(node_id for node_id, count in indegree.items() if count == 0))
    seen = 0
    while queue:
        source = queue.popleft()
        seen += 1
        for target in sorted(outgoing[source]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if seen != len(nodes):
        raise GraphError("graph contains a dependency cycle")
    if "active_wave" not in graph or "hard_stop" not in graph:
        raise GraphError("graph must declare active_wave and hard_stop")
    _validate_cancelled_waves(graph)
    active_wave = graph["active_wave"]
    running = {node_id for node_id, node in nodes.items() if node["status"] == "running"}
    active = active_nodes(active_wave, nodes, revision)
    if running != active:
        raise GraphError("running nodes must exactly match the active wave")
    if active_wave is not None:
        cursor = active_wave.get("transcript_cursor")
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 1:
            raise GraphError("active wave must carry a valid transcript cursor")
    if graph["hard_stop"] is not None and not isinstance(graph["hard_stop"], dict):
        raise GraphError("graph.hard_stop must be null or an object")
    hard_stop_nodes = [node_id for node_id, node in nodes.items() if node["status"] == "hard-stop"]
    if bool(hard_stop_nodes) != (graph["hard_stop"] is not None):
        raise GraphError("graph hard-stop state disagrees with its nodes")
    return root


def _core() -> ModuleType:
    """Load the installer-materialized v3 semantic core on demand."""
    try:
        import graph_semantics
    except ImportError as error:
        raise GraphError("schema-v3 graph semantics are not materialized; run install.sh") from error
    return graph_semantics


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            parsed: JsonValue = cast(JsonValue, json.load(handle))
            parsed_state = cast(object, parsed)
            root = cast(dict[str, Any], parsed_state) if isinstance(parsed_state, dict) else None
            if root is not None and root.get("schema_version") == 3:
                return cast(dict[str, Any], _core().validate(root))
            return _validate_state(cast(object, parsed))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise GraphError(f"cannot read valid state: {error}") from error


def _write(path: Path, state: dict[str, Any]) -> None:
    mode = path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


@contextmanager
def _locked(path: Path) -> Generator[None, None, None]:
    try:
        with Path(f"{path}.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    except OSError as error:
        raise GraphError(f"cannot lock state: {error}") from error


def _dependencies(state: dict[str, Any]) -> dict[str, set[str]]:
    graph = state["graph"]
    required: dict[str, set[str]] = {node_id: set() for node_id in graph["nodes"]}
    for edge in graph["edges"]:
        required[edge["to"]].add(edge["from"])
    for join_id, join in graph["joins"].items():
        required[join_id].update(join["inputs"])
    return required


def _release_joins(state: dict[str, Any]) -> list[str]:
    graph, released = state["graph"], cast(list[str], [])
    for join_id in sorted(graph["joins"]):
        join = graph["joins"][join_id]
        if join["released"]:
            continue
        if all(graph["nodes"][node_id]["status"] in SUCCESS for node_id in join["inputs"]):
            join["released"] = True
            graph["nodes"][join_id]["status"] = "done"
            graph["nodes"][join_id]["outcome"] = "done"
            released.append(join_id)
    return released


def _ready(state: dict[str, Any]) -> list[str]:
    graph, required = state["graph"], _dependencies(state)
    return sorted(
        node_id
        for node_id, node in graph["nodes"].items()
        if node_id not in graph["joins"]
        and node["status"] == "pending"
        and all(graph["nodes"][source]["status"] in SUCCESS for source in required[node_id])
    )


def _begin_wave(path: Path) -> dict[str, Any]:
    with _locked(path):
        state = _load(path)
        if state["schema_version"] == 3:
            transition = _core().begin_wave(state)
            proposed = cast(dict[str, Any], transition["state"])
            wave = cast(dict[str, Any], transition["wave"])
            proposed["graph"]["active_wave"]["transcript_cursor"] = transcript_cursor(proposed["session_id"])
            task_names = {
                node_id: task_name(node_id, proposed["graph"]["nodes"][node_id]["retry"]["attempts"] + 1)
                for node_id in wave["nodes"]
            }
            _write(path, proposed)
            return {
                "wave_id": wave["wave_id"],
                "nodes": wave["nodes"],
                "task_names": task_names,
                "revision": proposed["revision"],
            }
        graph = state["graph"]
        if graph["active_wave"] is not None:
            raise GraphError("an active wave already exists")
        if graph["hard_stop"] is not None:
            raise GraphError("the graph is hard-stopped")
        validate_evals(state, None, path.with_name("evals.json"))
        _release_joins(state)
        nodes = _ready(state)
        if not nodes:
            raise GraphError("no graph nodes are ready")
        cursor = transcript_cursor(state["session_id"])
        revision = state["revision"] + 1
        wave_id = f"wave-{revision}"
        for node_id in nodes:
            graph["nodes"][node_id]["status"] = "running"
            graph["nodes"][node_id]["outcome"] = "running"
        task_names = {
            node_id: task_name(node_id, graph["nodes"][node_id]["retry"]["attempts"] + 1) for node_id in nodes
        }
        graph["active_wave"] = {"id": wave_id, "revision": revision, "nodes": nodes, "transcript_cursor": cursor}
        state["revision"] = revision
        _write(path, state)
        return {"wave_id": wave_id, "nodes": nodes, "task_names": task_names, "revision": revision}


def _results(raw: object, active_wave: dict[str, Any]) -> dict[str, Any]:
    envelope = _object(raw, "results")
    if set(envelope) != {"wave_id", "results"}:
        raise GraphError("results must contain exactly wave_id and results")
    if envelope["wave_id"] != active_wave["id"]:
        raise GraphError("result wave id does not match the active wave")
    results = _object(envelope["results"], "results.results")
    if set(results) != set(active_wave["nodes"]):
        raise GraphError("result keys must exactly match the active wave")
    for node_id, raw_result in results.items():
        result = _object(raw_result, f"result {node_id}")
        if set(result) != {"outcome", "evidence"}:
            raise GraphError(f"result {node_id} must contain exactly outcome and evidence")
        if result.get("outcome") not in {"done", "skipped", "failed"}:
            raise GraphError(f"result {node_id} has invalid outcome")
        _nonempty(result.get("evidence"), f"result {node_id}.evidence")
    return results


def _cancel_unspawned_wave(path: Path, session: str) -> dict[str, Any]:
    with _locked(path):
        state = _load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        active_wave = state["graph"]["active_wave"]
        if active_wave is None:
            raise GraphError("no active wave exists")
        if has_current_wave_dispatch(state, active_wave):
            raise GraphError("an active wave with a worker spawn cannot be cancelled")
        for node_id in active_wave["nodes"]:
            node = state["graph"]["nodes"][node_id]
            node["status"] = "pending"
            node["outcome"] = "pending"
        state["graph"].setdefault("cancelled_waves", []).append(
            {"id": active_wave["id"], "revision": active_wave["revision"]}
        )
        state["graph"]["active_wave"] = None
        state["revision"] += 1
        _write(path, state)
        return {"cancelled_wave": active_wave["id"], "revision": state["revision"]}


def _acknowledge_cancelled_wave(path: Path, session: str, wave_id: str) -> dict[str, Any]:
    with _locked(path):
        state = _load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        active_wave = state["graph"]["active_wave"]
        expected_revision = state["revision"] - 2
        expected_wave = f"wave-{expected_revision}"
        if (
            active_wave is None
            or active_wave["revision"] != state["revision"]
            or state["graph"].get("cancelled_waves")
            or wave_id != expected_wave
        ):
            raise GraphError("only the immediately preceding unledgered wave can be acknowledged")
        state["graph"]["cancelled_waves"] = [{"id": wave_id, "revision": expected_revision}]
        _write(path, state)
        return {"acknowledged_wave": wave_id, "revision": state["revision"]}


def _add_remediation_node(path: Path, session: str, source_id: str, node_id: str) -> dict[str, Any]:
    with _locked(path):
        state = _load(path)
        graph = state["graph"]
        source = graph["nodes"].get(source_id)
        source = cast(dict[str, Any], source) if isinstance(source, dict) else None
        hard_stop = cast(dict[str, Any], graph["hard_stop"]) if isinstance(graph["hard_stop"], dict) else None
        if (
            state["session_id"] != session
            or graph["active_wave"] is not None
            or hard_stop is None
            or hard_stop.get("node") != source_id
            or hard_stop.get("reason") != "retry exhaustion"
            or source is None
            or source.get("status") != "hard-stop"
            or source["retry"]["attempts"] != source["retry"]["max"]
            or node_id in graph["nodes"]
            or not node_id.strip()
        ):
            raise GraphError("only an exhausted hard-stop node can receive one remediation successor")
        graph["nodes"][node_id] = {
            "status": "pending",
            "outcome": "pending",
            "retry": {"attempts": 0, "max": source["retry"]["max"]},
            "evidence": [],
        }
        for edge in graph["edges"]:
            if edge["to"] == source_id:
                edge["to"] = node_id
            if edge["from"] == source_id:
                edge["from"] = node_id
        source["status"] = "failed"
        source["outcome"] = "failed"
        graph["hard_stop"] = None
        _write(path, state)
        return {"remediation_node": node_id, "source_node": source_id, "revision": state["revision"]}


def _record_wave(path: Path, raw_results: str) -> dict[str, Any]:
    try:
        parsed_results: JsonValue = cast(JsonValue, json.loads(raw_results))
    except json.JSONDecodeError as error:
        raise GraphError(f"results are not valid JSON: {error}") from error
    with _locked(path):
        state = _load(path)
        graph = state["graph"]
        if graph["active_wave"] is None:
            raise GraphError("no active wave exists")
        if state["schema_version"] == 3:
            active = cast(dict[str, Any], graph["active_wave"])
            evidence_wave = dict(active)
            evidence_wave["id"] = active["wave_id"]
            references, identifiers = bind_worker_evidence(state, evidence_wave)
            envelope = _object(cast(object, parsed_results), "results")
            results = _object(envelope.get("results"), "results.results")
            if any(
                classify_worker_evidence(cast(dict[str, Any], result).get("evidence"), identifiers)[0]
                for result in results.values()
                if isinstance(result, dict)
            ):
                raise GraphError("result evidence must not contain worker evidence")
            try:
                transition = _core().record_wave(state, envelope.get("wave_id"), results)
            except ValueError as error:
                raise GraphError(str(error)) from error
            proposed = cast(dict[str, Any], transition["state"])
            for node_id, reference in references.items():
                proposed["graph"]["nodes"][node_id]["evidence"].append(reference)
            _write(path, proposed)
            return {
                "revision": proposed["revision"],
                "released_joins": transition["released_joins"],
                "ready": transition["ready"],
            }
        results = _results(cast(object, parsed_results), graph["active_wave"])
        references, identifiers = bind_worker_evidence(state, graph["active_wave"])
        if any(classify_worker_evidence(result["evidence"], identifiers)[0] for result in results.values()):
            raise GraphError("result evidence must not contain worker evidence")
        for node_id in sorted(results):
            result, node = results[node_id], graph["nodes"][node_id]
            node["evidence"].append(result["evidence"])
            node["evidence"].append(references[node_id])
            if result["outcome"] in {"done", "skipped"}:
                node["status"] = result["outcome"]
                node["outcome"] = result["outcome"]
                continue
            node["retry"]["attempts"] += 1
            if node["retry"]["attempts"] < node["retry"]["max"]:
                node["status"] = "pending"
                node["outcome"] = "pending"
                continue
            node["status"] = "hard-stop"
            node["outcome"] = "hard-stop"
            graph["hard_stop"] = {"node": node_id, "reason": "retry exhaustion", "evidence": result["evidence"]}
        graph["active_wave"] = None
        released = _release_joins(state)
        state["revision"] += 1
        _write(path, state)
        return {"revision": state["revision"], "released_joins": released, "ready": _ready(state)}


def _v3_transition(path: Path, session: str, operation: str, node: str, reason: str) -> dict[str, Any]:
    """Apply one v3-only core transition while retaining Codex file ownership."""
    with _locked(path):
        state = _load(path)
        if state["schema_version"] != 3:
            raise GraphError(f"{operation} is supported only for schema-v3 graphs")
        if state.get("session_id") != session:
            raise GraphError("session does not own this loop")
        try:
            transition = getattr(_core(), operation)(state, node, reason)
        except ValueError as error:
            raise GraphError(str(error)) from error
        proposed = cast(dict[str, Any], transition["state"])
        _write(path, proposed)
        key = "respawn" if operation == "respawn_stale" else "hard_stop"
        return cast(dict[str, Any], transition[key])


def _inspect(path: Path) -> dict[str, Any]:
    state = _load(path)
    graph = state["graph"]
    return {
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "revision": state["revision"],
        "status": state.get("status"),
        "active_wave": graph["active_wave"],
        "task_names": (
            {
                node_id: task_name(node_id, graph["nodes"][node_id]["retry"]["attempts"] + 1)
                for node_id in graph["active_wave"]["nodes"]
            }
            if graph["active_wave"] is not None
            else {}
        ),
        "running": sorted(node_id for node_id, node in graph["nodes"].items() if node["status"] == "running"),
        "ready": _ready(state) if graph["active_wave"] is None and graph["hard_stop"] is None else [],
        "hard_stop": graph["hard_stop"],
    }


def _validate_completion(
    state: dict[str, Any],
    session: str,
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> None:
    graph = state["graph"]
    if state["session_id"] != session:
        raise GraphError("session does not own this loop")
    if graph["active_wave"] is not None:
        raise GraphError("cannot complete with an active wave")
    unfinished = sorted(
        node_id for node_id, node in graph["nodes"].items() if node["status"] not in {"done", "skipped"}
    )
    if unfinished:
        raise GraphError(f"cannot complete unfinished nodes: {', '.join(unfinished)}")
    if graph["hard_stop"] is not None:
        raise GraphError("cannot complete a hard-stopped graph")
    unreleased = sorted(join_id for join_id, join in graph["joins"].items() if not join["released"])
    if unreleased:
        raise GraphError(f"cannot complete unreleased joins: {', '.join(unreleased)}")
    validate_worker_evidence(state)
    validate_completion_evidence(state, revision, evals_path, proof_path, retro_path, transcript_path)


def _complete(
    path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path, transcript_path: Path | None
) -> dict[str, Any]:
    with _locked(path):
        state = _load(path)
        if state["status"] == "complete":
            raise GraphError("graph is already complete")
        revision = state["revision"]
        _validate_completion(state, session, revision, evals_path, proof_path, retro_path, transcript_path)
        state["status"] = "complete"
        state["revision"] += 1
        state["completion"] = {"revision": revision}
        _write(path, state)
        return {"status": "complete", "loop_id": state["loop_id"], "revision": state["revision"]}


def _verify_completion(
    path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path, transcript_path: Path | None
) -> dict[str, Any]:
    state = _load(path)
    completion = _object(state.get("completion"), "completion")
    revision = completion.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise GraphError("graph completion revision must be an integer")
    if state["status"] != "complete" or revision != state["revision"] - 1:
        raise GraphError("graph has no valid completion record")
    _validate_completion(state, session, revision, evals_path, proof_path, retro_path, transcript_path)
    return {"status": "complete", "loop_id": state["loop_id"], "revision": state["revision"]}


def _authorize_dispatch(path: Path, session: str, task: str, evals_path: Path) -> dict[str, Any]:
    state = _load(path)
    if state["session_id"] != session:
        raise GraphError("session does not own this loop")
    if state["status"] == "complete":
        raise GraphError("completed graph does not own worker dispatch")
    node_id = task_node(task)
    active_wave = state["graph"]["active_wave"]
    if active_wave is None or node_id not in active_wave["nodes"]:
        raise GraphError("graph worker node is not in the active wave")
    attempt = state["graph"]["nodes"][node_id]["retry"]["attempts"] + 1
    if task_name(node_id, attempt) != task:
        raise GraphError("graph worker task name does not match the active attempt")
    validate_evals(state, None, evals_path)
    return {
        "loop_id": state["loop_id"],
        "node": node_id,
        "task_name": task,
        "wave_id": active_wave["id"],
        "revision": state["revision"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate one native Codex agentic-loop graph.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("begin-wave", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
    cancel = commands.add_parser("cancel-unspawned-wave")
    cancel.add_argument("state", type=Path)
    cancel.add_argument("--session", required=True)
    acknowledge = commands.add_parser("acknowledge-cancelled-wave")
    acknowledge.add_argument("state", type=Path)
    acknowledge.add_argument("--session", required=True)
    acknowledge.add_argument("--wave", required=True)
    remediate = commands.add_parser("add-remediation-node")
    remediate.add_argument("state", type=Path)
    remediate.add_argument("--session", required=True)
    remediate.add_argument("--source", required=True)
    remediate.add_argument("--node", required=True)
    record = commands.add_parser("record-wave")
    record.add_argument("state", type=Path)
    record.add_argument("results_json")
    for name in ("respawn_stale", "hard_stop"):
        transition = commands.add_parser(name.replace("_", "-"))
        transition.add_argument("state", type=Path)
        transition.add_argument("--session", required=True)
        transition.add_argument("--node", required=True)
        transition.add_argument("--reason", required=True)
    dispatch = commands.add_parser("authorize-dispatch")
    dispatch.add_argument("state", type=Path)
    for option in ("session", "task"):
        dispatch.add_argument(f"--{option}", required=True)
    dispatch.add_argument("--evals", required=True, type=Path)
    for name in ("complete", "verify-completion"):
        complete = commands.add_parser(name)
        complete.add_argument("state", type=Path)
        complete.add_argument("--session", required=True)
        for option in ("evals", "proof", "retro"):
            complete.add_argument(f"--{option}", required=True, type=Path)
        complete.add_argument("--transcript", type=Path)
    return parser


def main() -> int:
    """Run the requested graph command and print its JSON response."""
    args = _parser().parse_args()
    try:
        if args.command == "begin-wave":
            output = _begin_wave(args.state)
        elif args.command == "record-wave":
            output = _record_wave(args.state, args.results_json)
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = _v3_transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "inspect":
            output = _inspect(args.state)
        elif args.command == "authorize-dispatch":
            output = _authorize_dispatch(args.state, args.session, args.task, args.evals)
        elif args.command == "cancel-unspawned-wave":
            output = _cancel_unspawned_wave(args.state, args.session)
        elif args.command == "acknowledge-cancelled-wave":
            output = _acknowledge_cancelled_wave(args.state, args.session, args.wave)
        elif args.command == "add-remediation-node":
            output = _add_remediation_node(args.state, args.session, args.source, args.node)
        elif args.command == "complete":
            output = _complete(args.state, args.session, args.evals, args.proof, args.retro, args.transcript)
        else:
            output = _verify_completion(args.state, args.session, args.evals, args.proof, args.retro, args.transcript)
    except GraphError as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
