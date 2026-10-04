#!/usr/bin/env python3
"""Operate the filesystem-backed current native Codex agentic-loop graph."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_completion import complete, verify_completion
from graph_controller import add_unit, start
from graph_evidence import bind_worker_evidence, transcript_cursor, validate_evals
from graph_identity import GraphError, classify_worker_evidence, next_attempt, task_name, task_node
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import object_value as _object
from graph_io import write as _write
from graph_recovery import NODE_CODES, RecoveryRefusedError, node_lease, trace, traced_refusal
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


def _apply_record(state: dict[str, Any], raw_results: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind native evidence and compute the post-record state for exactly the active wave; writes nothing."""
    try:
        parsed_results: JsonValue = cast(JsonValue, json.loads(raw_results))
    except json.JSONDecodeError as error:
        raise GraphError(f"results are not valid JSON: {error}") from error
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
    return proposed, transition


def record_wave(path: Path, raw_results: str) -> dict[str, Any]:
    """Bind native evidence and atomically record exactly the active wave."""
    with _locked(path):
        state = _load(path)
        with traced_refusal(path, state, "record-wave"):
            proposed, transition = _apply_record(state, raw_results)
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


def _refuse(
    path: Path, state: dict[str, Any], error: RecoveryRefusedError, inputs: dict[str, Any]
) -> RecoveryRefusedError:
    """Trace a refusal naming the implicated nodes, then return the coded error for the caller to raise."""
    nodes = state["graph"]["nodes"]
    rows = [(n, next_attempt(nodes[n]), None) for n in error.nodes if n in nodes]
    trace(path, state, "refused", error.reason_code, inputs, rows)
    return error


def _recover_locked(path: Path, session: str, lease: int, clock: float, apply: bool) -> dict[str, Any]:
    """Classify, record `stale` and request every respawn inside one read-modify-write."""
    with _locked(path):
        state = _load(path)
        inputs: dict[str, object] = {"session": session, "lease": lease, "now": clock, "apply": apply}
        if state["session_id"] != session:
            foreign = RecoveryRefusedError("foreign_session", "session does not own this loop")
            raise _refuse(path, state, foreign, inputs)
        active = state["graph"]["active_wave"]
        if active is None:
            raise _refuse(path, state, RecoveryRefusedError("no_active_wave", "no active wave exists"), inputs)
        try:
            nodes = {node_id: node_lease(state, node_id, active, clock, lease) for node_id in active["nodes"]}
        except RecoveryRefusedError as error:
            raise _refuse(path, state, error, inputs) from error
        inputs["nodes"] = nodes
        kinds = set(nodes.values())
        uniform = len(kinds) == 1 and "stalled" not in kinds
        graph = state["graph"]
        rows = [(n, next_attempt(graph["nodes"][n]), action) for n, action in nodes.items()]
        report: dict[str, Any] = {
            "wave_id": active["wave_id"],
            "nodes": {node_id: {"action": action} for node_id, action in nodes.items()},
            "recovered": False,
            "reason_code": (
                NODE_CODES[next(iter(kinds))]
                if uniform
                else ("stalled_report_only" if len(kinds) == 1 else "mixed_wave")
            ),
        }
        if not apply or kinds != {"stalled"}:
            trace(path, state, "reported", report["reason_code"], inputs, rows)
            return report
        if spent := tuple(n for n in nodes if _budget_spent(graph["nodes"][n])):
            message = "recovery budget exhausted: waiting for human"
            raise _refuse(path, state, RecoveryRefusedError("recovery_budget_exhausted", message, spent), inputs)
        check = {"checked": True, "method": f"lease {lease}s expired", "result": "no worker activity"}
        results = {n: {"outcome": "stale", "evidence": "lease expired", "stale_check": check} for n in nodes}
        with traced_refusal(path, state, "recover-wave", session):
            proposed, _ = _apply_record(state, json.dumps({"wave_id": active["wave_id"], "results": results}))
        for node_id in nodes:
            try:
                respawned = graph_semantics.respawn_stale(proposed, node_id, "lease expired")
                proposed = cast(dict[str, Any], respawned["state"])
            except ValueError as error:
                raise GraphError(str(error)) from error
        graph_semantics.validate(proposed)
        _write(path, proposed)
        report.update(recovered=True, reason_code="recovered")
        trace(path, state, "recovered", "recovered", inputs, rows)
        return report


def recover_wave(
    path: Path, session: str, lease_seconds: int, now: float | None = None, apply: bool = True
) -> dict[str, Any]:
    """Recover an active wave whose every spawned worker is silent past the lease, in one locked save.

    A node with no spawn is only reported ("spawn it now"): nothing is recorded for it. Bounded: a node whose
    respawn generation has reached retry.max refuses recovery (fail closed, human decides).
    """
    return _recover_locked(path, session, lease_seconds, time.time() if now is None else now, apply)


def _budget_spent(node: dict[str, Any]) -> bool:
    """True when the node's respawn generation has reached its retry max."""
    return bool(node["respawn"]["generation"] >= node["retry"]["max"])


def summarize(path: Path) -> dict[str, Any]:
    """Plain-language status from graph state alone: done, active, ready, blocked and the human dependency."""
    state = _load(path)
    graph = state["graph"]
    statuses = {node_id: node["status"] for node_id, node in graph["nodes"].items()}
    pending = sorted(n for n, s in statuses.items() if s not in {"done", "skipped"})
    ready = [] if graph["active_wave"] or graph["hard_stop"] else graph_semantics.ready(state)
    if graph["hard_stop"] is not None:
        phase, detail = (
            "waiting for human",
            f"hard stop on {graph['hard_stop']['node']}: {graph['hard_stop']['reason']}",
        )
    elif graph["active_wave"] is not None:
        phase, detail = "waiting for worker", f"wave {graph['active_wave']['wave_id']} dispatched"
        spent = [n for n in graph["active_wave"]["nodes"] if _budget_spent(graph["nodes"][n])]
        if spent:
            detail += f"; recovery budget exhausted for {', '.join(spent)}: recover-wave will refuse, a human decides"
    elif ready:
        phase, detail = "ready to dispatch", "begin-wave then spawn the ready nodes"
    elif not pending:
        phase, detail = "ready to complete", "run verify-completion"
    else:
        phase, detail = "waiting for evidence", "no node is ready; check pending dependencies"
    return {
        "phase": phase,
        "detail": detail,
        "done": sorted(n for n in statuses if n not in pending),
        "active": list(graph["active_wave"]["nodes"]) if graph["active_wave"] else [],
        "ready": ready,
        "pending": pending,
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
    for name in ("begin-wave", "inspect", "summarize"):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
    for name in ("start", "add-unit"):
        controller = commands.add_parser(name)
        controller.add_argument("state", type=Path)
        controller.add_argument("--session", required=True)
        controller.add_argument("--loop-id", required=True)
        if name == "start":
            controller.add_argument("--prompt-file", required=True, type=Path)
        else:
            controller.add_argument("--unit", required=True)
            controller.add_argument("--depends-on", action="append", default=[])
            controller.add_argument("--join", action="store_true")
    recover = commands.add_parser("recover-wave")
    recover.add_argument("state", type=Path)
    recover.add_argument("--session", required=True)
    recover.add_argument("--lease-seconds", type=int, default=900)
    recover.add_argument("--report-only", action="store_true")
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
        if args.command == "start":
            output = start(args.state, args.session, args.loop_id, args.prompt_file)
        elif args.command == "add-unit":
            output = add_unit(args.state, args.session, args.loop_id, args.unit, args.depends_on, args.join)
        elif args.command == "begin-wave":
            output = begin_wave(args.state)
        elif args.command == "record-wave":
            output = record_wave(args.state, args.results_json)
        elif args.command == "record-unit":
            if (args.status == "done") != (args.evidence is not None):
                raise GraphError("done requires --evidence; dropped requires --reason")
            output = record_unit(args.state, args.session, args.unit, args.status, args.evidence or args.reason)
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "recover-wave":
            output = recover_wave(args.state, args.session, args.lease_seconds, apply=not args.report_only)
        elif args.command == "summarize":
            output = summarize(args.state)
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
