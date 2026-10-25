#!/usr/bin/env python3
"""Operate the filesystem-backed current native Codex agentic-loop graph."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, cast

import graph_dispatch
import graph_driver_cutover
import graph_invalid_dispatch
import graph_ledger
import graph_mutations
import graph_repair
import graph_semantics
import graph_spec
import graph_stops
from graph_completion import complete, verify_completion
from graph_controller import add_unit, instantiate, start
from graph_dispatch import apply_record as _apply_record
from graph_dispatch import authorize_dispatch as authorize_dispatch
from graph_dispatch import begin_wave as begin_wave
from graph_dispatch import record_wave as record_wave
from graph_identity import GraphError, next_attempt, task_name
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import write as _write
from graph_recovery import NODE_CODES, RecoveryRefusedError, node_lease, trace, traced_refusal
from graph_recovery import collection as collect
from graph_summary import budget_spent as _budget_spent
from graph_summary import summarize as summarize
from graph_vocab import DISPOSITION_KINDS

reject_invalid_dispatch = graph_invalid_dispatch.reject_invalid_dispatch


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


def record_repair(
    path: Path, session: str, unit: str, failed_node: str, kind: str, identity: str, diagnosis: str
) -> dict[str, Any]:
    """Record one conditional repair under the Codex state lock."""
    with _locked(path):
        try:
            proposed, report = graph_repair.record_repair(
                _load(path), session, unit, failed_node, kind, identity, diagnosis
            )
        except ValueError as error:
            raise GraphError(str(error)) from error
        _write(path, proposed)
        return report


def inspect(path: Path) -> dict[str, Any]:
    """Read core readiness and native task identities without mutating state."""
    state = _load(path)
    graph = state["graph"]
    return {
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "status": state.get("status"),
        **graph_semantics.inspect(state),
        "task_names": (
            {
                node_id: task_name(state["loop_id"], node_id, next_attempt(graph["nodes"][node_id]))
                for node_id in graph["active_wave"]["nodes"]
            }
            if graph["active_wave"] is not None
            else {}
        ),
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
    """Recover silent workers under one lock; report unspawned nodes and refuse exhausted retries."""
    if lease_seconds <= 0:  # a non-positive lease marks every live worker stalled
        raise RecoveryRefusedError("invalid_lease", "lease_seconds must be positive")
    return _recover_locked(path, session, lease_seconds, time.time() if now is None else now, apply)


def _add_unit_args(controller: argparse.ArgumentParser) -> None:
    """Register work-unit ownership and disposition fields."""
    controller.add_argument("--unit", required=True)
    controller.add_argument("--depends-on", action="append", default=[])
    controller.add_argument("--join", action="store_true")
    controller.add_argument("--manifest", action="append", default=[])
    controller.add_argument("--base-branch", help="remote branch used for first stacked publication")
    controller.add_argument("--worktree", help="absolute path of this unit's checkout")
    controller.add_argument("--model-role", help="dispatch model class: fast-mechanical | default | frontier")
    controller.add_argument("--write-scope", action="append", default=[], help="path the worker may write")
    controller.add_argument("--lesson", action="append", default=[], help="lesson the worker prompt must carry")
    controller.add_argument("--scope", help="one-line scope statement for the worker")
    controller.add_argument("--disposition", choices=DISPOSITION_KINDS, help="clean-break | preserve-compat")
    controller.add_argument("--named-blocker", help="what blocks removal (preserve-compat only)")
    controller.add_argument("--removal-ticket", help="ticket that removes it (preserve-compat only)")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Operate one native Codex agentic-loop graph.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("begin-wave", "inspect", "summarize", "collection"):
        command = commands.add_parser(name)
        command.add_argument("root" if name == "collection" else "state", type=Path)
    for name in ("start", "add-unit"):
        controller = commands.add_parser(name)
        controller.add_argument("state", type=Path)
        controller.add_argument("--session", required=True)
        controller.add_argument("--loop-id", required=True)
        if name == "start":
            controller.add_argument("--prompt-file", required=True, type=Path)
        else:
            _add_unit_args(controller)
    graph_dispatch.add_scope_arguments(commands)
    graph_ledger.add_parsers(commands.add_parser)
    spec = commands.add_parser("instantiate")
    spec.add_argument("state", type=Path)
    spec.add_argument("--session", required=True)
    spec.add_argument("--loop-id", required=True)
    spec.add_argument("--profile", choices=graph_spec.PROFILES, help="default: policy graph.profile")
    spec.add_argument("--unit", action="append", default=[], help="work unit id to register (repeatable)")
    convert = commands.add_parser("convert")
    convert.add_argument("state", type=Path)
    convert.add_argument("--session", required=True)
    mode = convert.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    recover = commands.add_parser("recover-wave")
    recover.add_argument("state", type=Path)
    recover.add_argument("--session", required=True)
    recover.add_argument("--lease-seconds", type=int, default=900)
    recover.add_argument("--report-only", action="store_true")
    reject = commands.add_parser("reject-invalid-dispatch")
    reject.add_argument("state", type=Path)
    reject.add_argument("--session", required=True)
    reject.add_argument("--node", required=True)
    reject.add_argument("--wave-id", required=True)
    reject.add_argument("--report-only", action="store_true")
    record = commands.add_parser("record-wave")
    record.add_argument("state", type=Path)
    record.add_argument("results_json")
    graph_driver_cutover.add_parsers(commands.add_parser)
    for name in ("record-decision", "flush-decisions"):
        decision = commands.add_parser(name)
        decision.add_argument("state", type=Path)
        decision.add_argument("--session", required=True)
        decision.add_argument("--cite-quote")
        if name == "record-decision":
            decision.add_argument("--loop-id", required=True)
            decision.add_argument("--revision", required=True, type=int)
            decision.add_argument("--phase", required=True)
            decision.add_argument("--decision", required=True)
            decision.add_argument("--flip-condition")
            decision.add_argument("--unit")
            decision.add_argument("--chosen", help="answer to a recorded worker status")
            decision.add_argument("--worker-status-seq", type=int, help="resolve this worker status with the decision")
            decision.add_argument(
                "--human-answer", action="store_true", help="a human answered an approval-gate status"
            )
    unit = commands.add_parser("record-unit")
    unit.add_argument("state", type=Path)
    unit.add_argument("--session", required=True)
    unit.add_argument("--unit", required=True)
    unit.add_argument("--status", required=True, choices=("done", "dropped"))
    detail = unit.add_mutually_exclusive_group(required=True)
    detail.add_argument("--evidence")
    detail.add_argument("--reason")
    repair = commands.add_parser("record-repair")
    repair.add_argument("state", type=Path)
    for field in ("session", "unit", "failed-node", "kind", "identity", "diagnosis"):
        repair.add_argument(f"--{field}", required=True)
    for name in ("respawn_stale", "hard_stop"):
        transition = commands.add_parser(name.replace("_", "-"))
        transition.add_argument("state", type=Path)
        transition.add_argument("--session", required=True)
        transition.add_argument("--node", required=True)
        transition.add_argument("--reason", required=True)
    graph_stops.add_parsers(commands.add_parser)
    dispatch = commands.add_parser("authorize-dispatch")
    dispatch.add_argument("state", type=Path)
    for option in ("session", "dispatch-id", "task-name"):
        dispatch.add_argument(f"--{option}", required=True)
    dispatch.add_argument("--message-file", required=True, type=Path)
    dispatch.add_argument("--agent-type", default="", help="the spawn_agent agent_type; empty when none was given")
    dispatch.add_argument("--tool-use-id", default="", help="native tool-call id from PreToolUse")
    dispatch.add_argument("--evals", type=Path, help="default: evals.json beside the state")
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
            fields: dict[str, Any] = {"model_role": args.model_role, "write_scope": args.write_scope}
            fields.update(lessons=args.lesson, disposition=(args.disposition, args.named_blocker, args.removal_ticket))
            output = add_unit(
                args.state,
                args.session,
                args.loop_id,
                args.unit,
                args.depends_on,
                args.join,
                args.manifest,
                {**fields, "scope": args.scope, "base_branch": args.base_branch, "worktree": args.worktree},
            )
        elif args.command in {"assign-unit-scope", "append-unit-scope-note"}:
            output = graph_dispatch.run_scope_command(args)
        elif args.command == "instantiate":
            output = instantiate(args.state, args.session, args.loop_id, args.profile, args.unit)
        elif args.command == "begin-wave":
            output = graph_dispatch.begin_wave(args.state)
        elif args.command == "record-wave":
            output = graph_dispatch.record_wave(args.state, args.results_json)
        elif args.command in graph_driver_cutover.COMMANDS:
            output = graph_driver_cutover.run(args)
        elif args.command == "record-unit":
            if (args.status == "done") != (args.evidence is not None):
                raise GraphError("done requires --evidence; dropped requires --reason")
            output = graph_mutations.record_unit(
                args.state, args.session, args.unit, args.status, args.evidence or args.reason
            )
        elif args.command == "record-decision":
            output = graph_mutations.record_decision(args)
        elif args.command == "flush-decisions":
            output = graph_mutations.flush_decisions(args)
        elif args.command == "record-repair":
            output = record_repair(
                args.state, args.session, args.unit, args.failed_node, args.kind, args.identity, args.diagnosis
            )
        elif args.command in {"stop", "consume-stop"}:
            output = graph_stops.run(args)
        elif args.command in graph_ledger.COMMANDS:
            output, code = graph_ledger.run(args)
            if code:
                print(json.dumps(output, sort_keys=True))
                return code
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "convert":
            output = graph_mutations.convert_state(args.state, args.session, args.check)
        elif args.command == "recover-wave":
            output = recover_wave(args.state, args.session, args.lease_seconds, apply=not args.report_only)
        elif args.command == "reject-invalid-dispatch":
            output = reject_invalid_dispatch(
                args.state, args.session, args.node, args.wave_id, apply=not args.report_only
            )
        elif args.command == "summarize":
            output = summarize(args.state)
        elif args.command == "collection":
            output = collect(args.root)
        elif args.command == "inspect":
            output = inspect(args.state)
        elif args.command == "authorize-dispatch":
            output = graph_dispatch.authorize_dispatch(
                args.state,
                args.session,
                args.dispatch_id,
                args.message_file,
                args.agent_type,
                args.task_name,
                args.evals or args.state.with_name("evals.json"),
                args.tool_use_id,
            )
        elif args.command == "complete":
            output = complete(args.state, args.session, args.evals, args.proof, args.retro, args.transcript)
        else:
            output = verify_completion(args.state, args.session, args.evals, args.proof, args.retro, args.transcript)
    except (GraphError, graph_semantics.GraphSemanticError) as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return int(output.get("exit_code", 0))


if __name__ == "__main__":
    raise SystemExit(main())
