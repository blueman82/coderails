#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
import tempfile
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


STATUSES = {"pending", "running", "done", "skipped", "hard-stop"}
SUCCESS = {"done", "skipped"}


class GraphError(ValueError):
    pass


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GraphError(f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphError(f"{label} must be a non-empty string")
    return value


def _validate_state(state: Any) -> dict[str, Any]:
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
        retry = _object(node.get("retry"), f"node {node_id}.retry")
        attempts, maximum = retry.get("attempts"), retry.get("max")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in (attempts, maximum)):
            raise GraphError(f"node {node_id} retry counts must be integers")
        if attempts < 0 or maximum < 1 or attempts > maximum:
            raise GraphError(f"node {node_id} has invalid retry bounds")
        if not isinstance(node.get("evidence"), list):
            raise GraphError(f"node {node_id}.evidence must be an array")

    edges = graph.get("edges")
    if not isinstance(edges, list):
        raise GraphError("graph.edges must be an array")
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
        inputs = join.get("inputs")
        if not isinstance(inputs, list) or not inputs or any(not isinstance(item, str) for item in inputs):
            raise GraphError(f"join {join_id}.inputs must be a non-empty unique array")
        if len(inputs) != len(set(inputs)):
            raise GraphError(f"join {join_id}.inputs must be a non-empty unique array")
        if any(item not in nodes or item == join_id for item in inputs):
            raise GraphError(f"join {join_id} references an unknown or identical input")
        dependencies[join_id].update(inputs)
        released = join["released"]
        join_done = nodes[join_id]["status"] == "done"
        if released != join_done:
            raise GraphError(f"join {join_id} release state disagrees with its node")

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
    active_wave = graph["active_wave"]
    if active_wave is not None:
        wave = _object(active_wave, "graph.active_wave")
        _nonempty(wave.get("id"), "graph.active_wave.id")
        wave_nodes = wave.get("nodes")
        if not isinstance(wave_nodes, list) or not wave_nodes or any(not isinstance(item, str) for item in wave_nodes):
            raise GraphError("graph.active_wave.nodes must be a non-empty unique array")
        if len(wave_nodes) != len(set(wave_nodes)):
            raise GraphError("graph.active_wave.nodes must be a non-empty unique array")
        if any(node_id not in nodes or nodes[node_id]["status"] != "running" for node_id in wave_nodes):
            raise GraphError("graph.active_wave must contain known running nodes")
    if any(node["status"] == "running" for node in nodes.values()) and active_wave is None:
        raise GraphError("running nodes require an active wave")
    if graph["hard_stop"] is not None and not isinstance(graph["hard_stop"], dict):
        raise GraphError("graph.hard_stop must be null or an object")
    hard_stop_nodes = [node_id for node_id, node in nodes.items() if node["status"] == "hard-stop"]
    if bool(hard_stop_nodes) != (graph["hard_stop"] is not None):
        raise GraphError("graph hard-stop state disagrees with its nodes")
    return root


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return _validate_state(json.load(handle))
    except (OSError, json.JSONDecodeError) as error:
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
def _locked(path: Path) -> Iterator[None]:
    try:
        with Path(f"{path}.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    except OSError as error:
        raise GraphError(f"cannot lock state: {error}") from error


def _dependencies(state: dict[str, Any]) -> dict[str, set[str]]:
    graph = state["graph"]
    required = {node_id: set() for node_id in graph["nodes"]}
    for edge in graph["edges"]:
        required[edge["to"]].add(edge["from"])
    for join_id, join in graph["joins"].items():
        required[join_id].update(join["inputs"])
    return required


def _release_joins(state: dict[str, Any]) -> list[str]:
    graph, released = state["graph"], []
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
        graph = state["graph"]
        if graph["active_wave"] is not None:
            raise GraphError("an active wave already exists")
        if graph["hard_stop"] is not None:
            raise GraphError("the graph is hard-stopped")
        _release_joins(state)
        nodes = _ready(state)
        if not nodes:
            raise GraphError("no graph nodes are ready")
        revision = state["revision"] + 1
        wave_id = f"wave-{revision}"
        for node_id in nodes:
            graph["nodes"][node_id]["status"] = "running"
            graph["nodes"][node_id]["outcome"] = "running"
        graph["active_wave"] = {"id": wave_id, "nodes": nodes}
        state["revision"] = revision
        _write(path, state)
        return {"wave_id": wave_id, "nodes": nodes, "revision": revision}


def _results(raw: Any, active_wave: dict[str, Any]) -> dict[str, Any]:
    envelope = _object(raw, "results")
    if "results" in envelope or "wave_id" in envelope:
        if envelope.get("wave_id") != active_wave["id"]:
            raise GraphError("result wave id does not match the active wave")
        envelope = _object(envelope.get("results"), "results.results")
    if set(envelope) != set(active_wave["nodes"]):
        raise GraphError("result keys must exactly match the active wave")
    for node_id, raw_result in envelope.items():
        result = _object(raw_result, f"result {node_id}")
        if result.get("outcome") not in {"done", "skipped", "failed"}:
            raise GraphError(f"result {node_id} has invalid outcome")
        _nonempty(result.get("evidence"), f"result {node_id}.evidence")
    return envelope


def _record_wave(path: Path, raw_results: str) -> dict[str, Any]:
    try:
        parsed_results = json.loads(raw_results)
    except json.JSONDecodeError as error:
        raise GraphError(f"results are not valid JSON: {error}") from error
    with _locked(path):
        state = _load(path)
        graph = state["graph"]
        if graph["active_wave"] is None:
            raise GraphError("no active wave exists")
        results = _results(parsed_results, graph["active_wave"])
        for node_id in sorted(results):
            result, node = results[node_id], graph["nodes"][node_id]
            node["evidence"].append(result["evidence"])
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
            graph["hard_stop"] = {
                "node": node_id,
                "reason": "retry exhaustion",
                "evidence": result["evidence"],
            }
        graph["active_wave"] = None
        released = _release_joins(state)
        state["revision"] += 1
        _write(path, state)
        return {"revision": state["revision"], "released_joins": released, "ready": _ready(state)}


def _inspect(path: Path) -> dict[str, Any]:
    state = _load(path)
    graph = state["graph"]
    return {
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "revision": state["revision"],
        "status": state.get("status"),
        "active_wave": graph["active_wave"],
        "running": sorted(node_id for node_id, node in graph["nodes"].items() if node["status"] == "running"),
        "ready": _ready(state) if graph["active_wave"] is None and graph["hard_stop"] is None else [],
        "hard_stop": graph["hard_stop"],
    }


def _load_evidence(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return _object(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as error:
        raise GraphError(f"{label} is missing or invalid: {error}") from error


def _matching_evidence(evidence: dict[str, Any], state: dict[str, Any], label: str) -> None:
    if evidence.get("session_id") != state["session_id"] or evidence.get("loop_id") != state["loop_id"]:
        raise GraphError(f"{label} belongs to a different loop")


def _complete(path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path) -> dict[str, Any]:
    with _locked(path):
        state = _load(path)
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

        evals = _load_evidence(evals_path, "evals")
        proof = _load_evidence(proof_path, "proof")
        retro = _load_evidence(retro_path, "retro")
        for label, evidence in (("evals", evals), ("proof", proof), ("retro", retro)):
            _matching_evidence(evidence, state, label)
        if evals.get("revision") != state["revision"]:
            raise GraphError("evals revision does not match the graph")
        if evals.get("result") not in {"GO", "VERIFICATION_LEVEL0"}:
            raise GraphError("evals are not graded GO")
        grading = evals.get("grading")
        if not isinstance(grading, dict) or not grading.get("by") or not grading.get("checksum"):
            raise GraphError("evals grading stamp is missing")
        proofs = proof.get("proofs")
        if not isinstance(proofs, list) or not proofs or any(item.get("status") != "pass" for item in proofs if isinstance(item, dict)):
            raise GraphError("proof evidence is missing or not passing")
        if any(not isinstance(item, dict) for item in proofs):
            raise GraphError("proof evidence is malformed")
        if not isinstance(retro.get("schema_version"), int) or retro["schema_version"] < 1 or retro.get("status") != "complete":
            raise GraphError("retro evidence is incomplete")
        state["status"] = "complete"
        state["revision"] += 1
        _write(path, state)
        return {"status": "complete", "loop_id": state["loop_id"], "revision": state["revision"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate one native Codex agentic-loop graph.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("begin-wave", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
    record = commands.add_parser("record-wave")
    record.add_argument("state", type=Path)
    record.add_argument("results_json")
    complete = commands.add_parser("complete")
    complete.add_argument("state", type=Path)
    complete.add_argument("--session", required=True)
    complete.add_argument("--evals", required=True, type=Path)
    complete.add_argument("--proof", required=True, type=Path)
    complete.add_argument("--retro", required=True, type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "begin-wave":
            output = _begin_wave(args.state)
        elif args.command == "record-wave":
            output = _record_wave(args.state, args.results_json)
        elif args.command == "inspect":
            output = _inspect(args.state)
        else:
            output = _complete(args.state, args.session, args.evals, args.proof, args.retro)
    except GraphError as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
