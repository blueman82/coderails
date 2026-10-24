#!/usr/bin/env python3
"""Operate the native Claude schema-v3 graph through its provider-owned adapter."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import graph_convert
import graph_driver_controller
import graph_driver_mode
import graph_repair
import graph_spec
from graph_vocab import DISPOSITION_KINDS, STOP_CATEGORIES, STOP_REASON_CODES, disposition_report

from hooks.scripts.lib import (
    graph_controller,
    graph_decisions,
    graph_driver_adapter,
    graph_driver_claude,
    graph_recovery,
    graph_stops,
)
from hooks.scripts.lib import graph_dispatch as dispatch
from hooks.scripts.lib.graph_evidence import object_value
from hooks.scripts.lib.graph_evidence_revalidate import revalidate_all
from hooks.scripts.lib.graph_executor import graph_semantics, load, transition, validate_state
from hooks.scripts.lib.graph_recovery import trace
from hooks.scripts.lib.loop_state_common import atomic_progress_update

GRAPH_COMMANDS = (
    "start",
    "add-unit",
    "assign-unit-scope",
    "instantiate",
    "inspect",
    "summarize",
    "recover-wave",
    "plan",
    "begin-wave",
    "begin-driver-wave",
    "drive",
    "record-wave",
    "record-driver-wave",
    "record-driver-control",
    "record-unit",
    "record-repair",
    "respawn-stale",
    "hard-stop",
    "stop",
    "authorize-dispatch",
    "authorize-driver",
    "complete",
    "verify-completion",
    "convert",
    "cutover-driver",
    "disposition-audit",
    "record-decision",
)


def parser() -> argparse.ArgumentParser:
    """Expose current semantic operations and native completion checks."""
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in GRAPH_COMMANDS:
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
        if name in {"record-wave", "record-driver-wave"}:
            command.add_argument("results_json")
        if name == "record-unit":
            command.add_argument("--unit", required=True)
            command.add_argument("--status", required=True, choices=("done", "dropped"))
            detail = command.add_mutually_exclusive_group(required=True)
            detail.add_argument("--evidence")
            detail.add_argument("--reason")
        if name == "record-repair":
            for field in ("session", "unit", "failed-node", "kind", "identity", "diagnosis"):
                command.add_argument(f"--{field}", required=True)
        if name in {"start", "add-unit", "instantiate"}:
            command.add_argument("--session", required=True)
            command.add_argument("--loop-id", required=True)
        if name == "authorize-driver":
            for field in ("session", "dispatch-id", "role", "driver-run-id"):
                command.add_argument(f"--{field}", required=True)
            command.add_argument("--prompt-file", required=True, type=Path)
        if name in {"record-driver-control", "drive", "assign-unit-scope"}:
            graph_driver_adapter.add_arguments(name, command)
        if name == "instantiate":
            command.add_argument("--profile", choices=graph_spec.PROFILES, help="default: policy graph.profile")
            command.add_argument("--unit", action="append", default=[], help="work unit id to register (repeatable)")
        if name == "start":
            command.add_argument("--prompt-file", required=True, type=Path)
        if name == "add-unit":
            command.add_argument("--unit", required=True)
            command.add_argument("--depends-on", action="append", default=[])
            command.add_argument("--join", action="store_true")
            command.add_argument("--manifest", action="append", default=[])
            command.add_argument("--base-branch", help="remote branch used for first stacked publication")
            command.add_argument("--worktree", help="absolute path of this unit's checkout")
            command.add_argument("--model-role", help="dispatch model class: fast-mechanical | default | frontier")
            command.add_argument("--write-scope", action="append", default=[], help="path the worker may write")
            command.add_argument("--lesson", action="append", default=[], help="lesson the worker prompt must carry")
            command.add_argument("--scope", help="one-line scope statement for the worker")
            command.add_argument("--disposition", choices=DISPOSITION_KINDS, help="clean-break | preserve-compat")
            command.add_argument("--named-blocker", help="what blocks removal (preserve-compat only)")
            command.add_argument("--removal-ticket", help="ticket that removes it (preserve-compat only)")
        if name == "convert":
            mode = command.add_mutually_exclusive_group()
            mode.add_argument("--check", action="store_true", help="report the conversion without writing")
            mode.add_argument("--write", action="store_true", help="convert in place (the default)")
        if name == "recover-wave":
            command.add_argument("--lease-seconds", type=int, default=900)
            command.add_argument("--report-only", action="store_true")
        if name == "stop":
            command.add_argument("--category", required=True, choices=STOP_CATEGORIES)
            command.add_argument("--reason-code", required=True, choices=STOP_REASON_CODES)
            command.add_argument("--reason", required=True)
        if name in {
            "stop",
            "respawn-stale",
            "hard-stop",
            "authorize-dispatch",
            "record-unit",
            "record-decision",
            "complete",
            "verify-completion",
            "recover-wave",
            "convert",
            "cutover-driver",
        }:
            command.add_argument("--session", required=True)
        if name in {"respawn-stale", "hard-stop"}:
            command.add_argument("--node", required=True)
            command.add_argument("--reason", required=True)
        if name == "record-decision":
            for flag in ("--phase", "--decision", "--chosen"):
                command.add_argument(flag, required=True)
            command.add_argument("--flip-condition", help="what would change this decision")
            command.add_argument("--worker-status-seq", type=int, help="mark this worker_statuses row resolved")
            command.add_argument("--human-answer", action="store_true", help="a human answered")
        if name == "authorize-dispatch":
            command.add_argument("--prompt", required=True)
            command.add_argument("--subagent-type", required=True)
            command.add_argument("--tool-use-id", help="PreToolUse tool_use_id; makes a retried hook idempotent")
    return result


def native_transition(path: Path, session: str, operation: str, node: str, reason: str) -> dict[str, Any]:
    """Apply one pure transition under the sole Claude lock and owner check."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        if state["session_id"] != session:
            raise ValueError("session does not own this graph")
        transform = graph_semantics.respawn_stale if operation == "respawn_stale" else graph_semantics.hard_stop
        proposal = transform(state, node, reason)
        output.update({key: value for key, value in proposal.items() if key != "state"})
        return object_value(proposal["state"], "proposed graph")

    transition(path, update)
    return output


def record_stop(path: Path, session: str, category: str, reason_code: str, reason: str) -> dict[str, Any]:
    """Append one stop-intent row under the sole Claude lock and owner check."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        proposal = graph_stops.record_stop(state, session, category, reason_code, reason)
        output.update(proposal["stop"])
        return object_value(proposal["state"], "proposed graph")

    transition(path, update)
    return output


class _NoWriteError(ValueError):
    """Abort the locked update without writing: a check run or an already-current state."""


def convert_state(path: Path, session: str, check: bool) -> dict[str, Any]:
    """Convert progress.json to the current minor under the sole Claude lock; refuse ambiguity, never guess."""
    inputs: dict[str, Any] = {"session": session, "check": check}
    report: dict[str, Any] = {}
    backup: list[Path] = []
    refusal: list[graph_convert.ConvertRefusedError] = []

    def update(raw: dict[str, Any]) -> dict[str, Any]:
        try:
            converted, found = graph_convert.convert(raw, session)
            report.update(found)
            if check or not found["changed"]:
                raise _NoWriteError
            try:
                validate_state(converted)
            except ValueError as error:
                raise graph_convert.ConvertRefusedError("invalid_result", str(error)) from error
            backup.append(graph_convert.write_backup(path))
            return converted
        except graph_convert.ConvertRefusedError as error:
            refusal.append(error)
            raise

    saved = atomic_progress_update(path, update)
    if refusal:
        trace(path, {"session_id": session}, "refused", f"convert_refused_{refusal[0].code}", inputs, [], "convert")
        raise refusal[0]
    if not saved and not report:
        raise ValueError("progress.json is locked, unreadable or not an object")
    if saved:
        load(path)  # re-validate what was just written; the .pre-convert backup remains for manual recovery
    trace(path, {"session_id": session}, "ok", "convert_ok", inputs, [], "convert")
    return {**report, "check": check, "backup": backup[0].name if backup else None}


def cutover_driver(path: Path, session: str) -> dict[str, Any]:
    """Verify retained native history, then mark one driver-only wave boundary."""
    output: dict[str, Any] = {}
    refusal: list[str] = []

    def update(state: dict[str, Any]) -> dict[str, Any]:
        try:
            validate_state(state)
            if state["session_id"] != session:
                raise ValueError("session does not own this loop")
            if state.get("state_minor", 0) < 2:
                raise ValueError("run graph.py convert before driver cutover")
            result = graph_driver_mode.cutover(state, hashlib.sha256(path.read_bytes()).hexdigest())
            graph = state["graph"]
            fresh = not graph.get("wave_history") and all(
                node["status"] == "pending" and node["retry"]["attempts"] == 0 and not node["evidence"]
                for node in graph["nodes"].values()
            )
            if not fresh:
                revalidate_all(state)
            proposed = object_value(result["state"], "driver cutover state")
            graph_semantics.validate(proposed)
            graph_convert.write_backup(path, ".pre-driver")
            output.update(revision=proposed["revision"], driver_from_revision=result["driver_from_revision"])
            return proposed
        except ValueError as error:
            refusal.append(str(error))
            raise

    if not atomic_progress_update(path, update):
        raise ValueError(refusal[0] if refusal else "progress.json is locked or unreadable")
    trace(path, {"session_id": session}, "ok", "driver_cutover", {}, [], "cutover-driver")
    return output


def record_repair(
    path: Path, session: str, unit: str, failed_node: str, kind: str, identity: str, diagnosis: str
) -> dict[str, Any]:
    """Record a bounded, distinct repair under the Claude state lock."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        proposed, report = graph_repair.record_repair(state, session, unit, failed_node, kind, identity, diagnosis)
        output.update(report)
        return proposed

    transition(path, update)
    return output


def main() -> int:
    """Run one explicit graph operation with fail-closed CLI status."""
    args = parser().parse_args()
    try:
        if args.command == "start":
            output: object = graph_controller.start(args.state, args.session, args.loop_id, args.prompt_file)
        elif args.command == "add-unit":
            fields: dict[str, Any] = {"model_role": args.model_role, "write_scope": args.write_scope}
            fields.update(lessons=args.lesson, disposition=(args.disposition, args.named_blocker, args.removal_ticket))
            output = graph_controller.add_unit(
                args.state,
                args.session,
                args.loop_id,
                args.unit,
                args.depends_on,
                args.join,
                args.manifest,
                {**fields, "scope": args.scope, "base_branch": args.base_branch, "worktree": args.worktree},
            )
        elif args.command == "assign-unit-scope":
            output = graph_driver_adapter.assign_scope(args.state, args.session, args.unit, args.scope)
        elif args.command == "instantiate":
            output = graph_controller.instantiate(args.state, args.session, args.loop_id, args.profile, args.unit)
        elif args.command == "inspect":
            state = load(args.state)
            output = {
                "session_id": state["session_id"],
                "loop_id": state["loop_id"],
                **graph_semantics.inspect(state),
            }
        elif args.command == "summarize":
            output = graph_recovery.summarize(load(args.state))
        elif args.command == "record-decision":
            typed: dict[str, str | None] = {"phase": args.phase, "decision": args.decision, "chosen": args.chosen}
            typed["flip_condition"] = args.flip_condition
            output = graph_decisions.record_decision(
                args.state, args.session, typed, args.worker_status_seq, args.human_answer
            )
        elif args.command == "disposition-audit":
            report = disposition_report(load(args.state).get("work_units"))
            output = report
            if report["offenders"]:
                print(json.dumps(report, sort_keys=True))
                print("graph: preserve-compat units must carry a named blocker and removal ticket", file=sys.stderr)
                return 1
        elif args.command == "recover-wave":
            output = dispatch.recover_wave(args.state, args.session, args.lease_seconds, apply=not args.report_only)
        elif args.command == "plan":
            output = dispatch.plan(args.state)
        elif args.command == "begin-wave":
            output = dispatch.begin_wave(args.state)
        elif args.command == "record-wave":
            output = dispatch.record_wave(args.state, object_value(json.loads(args.results_json), "wave report"))
        elif args.command == "record-driver-wave":
            output = graph_driver_adapter.record_wave(
                args.state, object_value(json.loads(args.results_json), "driver wave report")
            )
        elif args.command == "record-driver-control":
            output = graph_driver_adapter.record_control(args.state, args.session, args.node, args.result_file)
        elif args.command == "begin-driver-wave":
            output = graph_driver_adapter.begin_wave(args.state)
        elif args.command == "drive":
            checkouts = graph_driver_controller.select_checkouts(args.checkout, args.checkout_map)
            output = graph_driver_claude.run_wave(
                args.state, args.session, checkouts, Path(__file__), graph_driver_controller.drive_wave
            )
        elif args.command == "authorize-driver":
            output = graph_driver_adapter.authorize(
                args.state, args.session, args.dispatch_id, args.prompt_file, args.role, args.driver_run_id
            )
        elif args.command == "record-unit":
            if (args.status == "done") != (args.evidence is not None):
                raise ValueError("done requires --evidence; dropped requires --reason")
            output = graph_controller.record_unit(
                args.state, args.session, args.unit, args.status, args.evidence or args.reason
            )
        elif args.command == "record-repair":
            output = record_repair(
                args.state, args.session, args.unit, args.failed_node, args.kind, args.identity, args.diagnosis
            )
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = native_transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "stop":
            output = record_stop(args.state, args.session, args.category, args.reason_code, args.reason)
        elif args.command == "convert":
            output = convert_state(args.state, args.session, args.check)
        elif args.command == "cutover-driver":
            output = cutover_driver(args.state, args.session)
        elif args.command == "authorize-dispatch":
            output = dispatch.authorize_dispatch(
                args.state, args.session, args.prompt, args.subagent_type, args.tool_use_id
            )
        else:
            output = dispatch.complete(args.state, args.session, args.command == "complete")
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
