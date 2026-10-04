#!/usr/bin/env python3
"""Operate the filesystem-backed current native Codex agentic-loop graph."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_completion import complete, verify_completion
from graph_evidence import bind_worker_evidence, transcript_cursor, validate_evals
from graph_identity import GraphError, classify_worker_evidence, next_attempt, task_name, task_node
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import object_value as _object
from graph_io import write as _write
from json_types import JsonValue


def begin_wave(path: Path) -> dict[str, Any]:
    """Start one core wave under the native state lock and frozen eval gate."""
    with _locked(path):
        state = _load(path)
        validate_evals(state, None, path.with_name("evals.json"))
        transition = graph_semantics.begin_wave(state)
        proposed = cast(dict[str, Any], transition["state"])
        wave = cast(dict[str, Any], transition["wave"])
        proposed["graph"]["active_wave"]["transcript_cursor"] = transcript_cursor(proposed["session_id"])
        task_names = {
            node_id: task_name(proposed["loop_id"], node_id, next_attempt(proposed["graph"]["nodes"][node_id]))
            for node_id in wave["nodes"]
        }
        graph_semantics.validate(proposed)
        _write(path, proposed)
        return {
            "wave_id": wave["wave_id"],
            "nodes": wave["nodes"],
            "task_names": task_names,
            "revision": proposed["revision"],
        }


def record_wave(path: Path, raw_results: str) -> dict[str, Any]:
    """Bind native evidence and atomically record exactly the active wave."""
    try:
        parsed_results: JsonValue = cast(JsonValue, json.loads(raw_results))
    except json.JSONDecodeError as error:
        raise GraphError(f"results are not valid JSON: {error}") from error
    with _locked(path):
        state = _load(path)
        graph = state["graph"]
        if graph["active_wave"] is None:
            raise GraphError("no active wave exists")
        active = cast(dict[str, Any], graph["active_wave"])
        envelope = _object(cast(object, parsed_results), "results")
        if set(envelope) != {"wave_id", "results"}:
            raise GraphError("results must contain exactly wave_id and results")
        results = _object(envelope.get("results"), "results.results")
        transition = graph_semantics.record_wave(state, envelope.get("wave_id"), results)
        stale_nodes = frozenset(node for node, result in results.items() if result["outcome"] == "stale")
        failed_nodes = frozenset(node for node, result in results.items() if result["outcome"] == "failed")
        references, identifiers = bind_worker_evidence(state, active, stale_nodes, failed_nodes)
        if any(
            classify_worker_evidence(cast(dict[str, Any], result).get("evidence"), identifiers)[0]
            for result in results.values()
            if isinstance(result, dict)
        ):
            raise GraphError("result evidence must not contain worker evidence")
        proposed = cast(dict[str, Any], transition["state"])
        for node_id, reference in references.items():
            proposed["graph"]["nodes"][node_id]["evidence"].append(reference)
        graph_semantics.validate(proposed)
        _write(path, proposed)
        return {
            "revision": proposed["revision"],
            "released_joins": transition["released_joins"],
            "ready": transition["ready"],
        }


def transition(path: Path, session: str, operation: str, node: str, reason: str) -> dict[str, Any]:
    """Apply one v3-only core transition while retaining Codex file ownership."""
    with _locked(path):
        state = _load(path)
        if state.get("session_id") != session:
            raise GraphError("session does not own this loop")
        try:
            transition = getattr(graph_semantics, operation)(state, node, reason)
        except ValueError as error:
            raise GraphError(str(error)) from error
        proposed = cast(dict[str, Any], transition["state"])
        graph_semantics.validate(proposed)
        _write(path, proposed)
        key = "respawn" if operation == "respawn_stale" else "hard_stop"
        return cast(dict[str, Any], transition[key])


def record_unit(path: Path, session: str, unit_id: str, status: str, detail: str) -> dict[str, Any]:
    """Record an independently checked work-unit decision under the state lock."""
    with _locked(path):
        state = _load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
            raise GraphError("work unit requires an in-progress graph without an active wave")
        units = cast(object, state.get("work_units"))
        if not isinstance(cast(object, unit_id), str) or not unit_id.strip() or not isinstance(units, dict):
            raise GraphError("work unit must be registered")
        unit = cast(dict[str, object], units).get(unit_id)
        if not isinstance(unit, dict):
            raise GraphError("work unit must be registered and pending")
        record = cast(dict[str, object], unit)
        if record.get("status") != "pending":
            raise GraphError("work unit must be registered and pending")
        if status not in {"done", "dropped"} or not isinstance(cast(object, detail), str) or not detail.strip():
            raise GraphError("work unit decision requires a status and nonblank evidence or reason")
        record["status"] = status
        record["evidence" if status == "done" else "dropped_reason"] = detail.strip()
        graph_semantics.validate(state)
        _write(path, state)
        return {"unit": unit_id, "status": status, "revision": state["revision"]}


def inspect(path: Path) -> dict[str, Any]:
    """Read core readiness and native task identities without mutating state."""
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
                node_id: task_name(state["loop_id"], node_id, next_attempt(graph["nodes"][node_id]))
                for node_id in graph["active_wave"]["nodes"]
            }
            if graph["active_wave"] is not None
            else {}
        ),
        "running": sorted(node_id for node_id, node in graph["nodes"].items() if node["status"] == "running"),
        "ready": graph_semantics.ready(state) if graph["active_wave"] is None and graph["hard_stop"] is None else [],
        "hard_stop": graph["hard_stop"],
    }


def authorize_dispatch(path: Path, session: str, task: str, evals_path: Path) -> dict[str, Any]:
    """Require session, active attempt, and frozen eval authority before dispatch."""
    state = _load(path)
    if state["session_id"] != session:
        raise GraphError("session does not own this loop")
    if state["status"] == "complete":
        raise GraphError("completed graph does not own worker dispatch")
    loop_id, node_id = task_node(task)
    if loop_id != state["loop_id"]:
        raise GraphError("graph worker task name belongs to another loop")
    active_wave = state["graph"]["active_wave"]
    if active_wave is None or node_id not in active_wave["nodes"]:
        raise GraphError("graph worker node is not in the active wave")
    attempt = next_attempt(state["graph"]["nodes"][node_id])
    if task_name(state["loop_id"], node_id, attempt) != task:
        raise GraphError("graph worker task name does not match the active attempt")
    validate_evals(state, None, evals_path)
    return {
        "loop_id": state["loop_id"],
        "node": node_id,
        "task_name": task,
        "wave_id": active_wave["wave_id"],
        "revision": state["revision"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate one native Codex agentic-loop graph.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("begin-wave", "inspect"):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
    record = commands.add_parser("record-wave")
    record.add_argument("state", type=Path)
    record.add_argument("results_json")
    unit = commands.add_parser("record-unit")
    unit.add_argument("state", type=Path)
    unit.add_argument("--session", required=True)
    unit.add_argument("--unit", required=True)
    unit.add_argument("--status", required=True, choices=("done", "dropped"))
    detail = unit.add_mutually_exclusive_group(required=True)
    detail.add_argument("--evidence")
    detail.add_argument("--reason")
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
            output = begin_wave(args.state)
        elif args.command == "record-wave":
            output = record_wave(args.state, args.results_json)
        elif args.command == "record-unit":
            if (args.status == "done") != (args.evidence is not None):
                raise GraphError("done requires --evidence; dropped requires --reason")
            output = record_unit(args.state, args.session, args.unit, args.status, args.evidence or args.reason)
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "inspect":
            output = inspect(args.state)
        elif args.command == "authorize-dispatch":
            output = authorize_dispatch(args.state, args.session, args.task, args.evals)
        elif args.command == "complete":
            output = complete(args.state, args.session, args.evals, args.proof, args.retro, args.transcript)
        else:
            output = verify_completion(args.state, args.session, args.evals, args.proof, args.retro, args.transcript)
    except (GraphError, graph_semantics.GraphSemanticError) as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
