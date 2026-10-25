#!/usr/bin/env python3
"""Operate the native Claude schema-v3 graph through its provider-owned adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import graph_convert
import graph_repair
import graph_spec
from graph_vocab import STOP_CATEGORIES, STOP_REASON_CODES

from hooks.scripts.lib import graph_controller, graph_recovery, graph_stops
from hooks.scripts.lib import graph_dispatch as dispatch
from hooks.scripts.lib.graph_evidence import object_value
from hooks.scripts.lib.graph_executor import graph_semantics, load, transition, validate_state
from hooks.scripts.lib.graph_recovery import trace
from hooks.scripts.lib.loop_state_common import atomic_progress_update
from scripts.lib import decision_record


def parser() -> argparse.ArgumentParser:
    """Expose only current semantic operations and native completion checks."""
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in (
        "start",
        "add-unit",
        "instantiate",
        "inspect",
        "summarize",
        "collection",
        "recover-wave",
        "plan",
        "begin-wave",
        "record-wave",
        "record-unit",
        "record-decision",
        "flush-decisions",
        "record-repair",
        "record-proof-disposition",
        "respawn-stale",
        "hard-stop",
        "stop",
        "authorize-dispatch",
        "complete",
        "verify-completion",
        "convert",
    ):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
        if name == "record-wave":
            command.add_argument("results_json")
        if name in {"record-decision", "flush-decisions"}:
            command.add_argument("--session", required=True)
            command.add_argument("--cite-quote")
        if name == "record-decision":
            command.add_argument("--loop-id", required=True)
            command.add_argument("--revision", required=True, type=int)
            command.add_argument("--phase", required=True)
            command.add_argument("--decision", required=True)
            command.add_argument("--flip-condition")
            command.add_argument("--unit")
        if name == "record-unit":
            command.add_argument("--unit", required=True)
            command.add_argument("--status", required=True, choices=("done", "dropped"))
            detail = command.add_mutually_exclusive_group(required=True)
            detail.add_argument("--evidence")
            detail.add_argument("--reason")
        if name == "record-repair":
            for field in ("session", "unit", "failed-node", "kind", "identity", "diagnosis"):
                command.add_argument(f"--{field}", required=True)
        if name == "record-proof-disposition":
            command.add_argument("--loop-id", required=True)
            command.add_argument("--revision", required=True, type=int)
            command.add_argument("--disposition", required=True)
            command.add_argument("--reason", required=True)
        if name in {"start", "add-unit", "instantiate"}:
            command.add_argument("--session", required=True)
            command.add_argument("--loop-id", required=True)
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
        if name == "recover-wave":
            command.add_argument("--lease-seconds", type=int, default=900)
            command.add_argument("--report-only", action="store_true")
        if name == "convert":
            mode = command.add_mutually_exclusive_group()
            mode.add_argument("--check", action="store_true")
            mode.add_argument("--write", action="store_true")
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
            "record-proof-disposition",
            "complete",
            "verify-completion",
            "recover-wave",
            "convert",
        }:
            command.add_argument("--session", required=True)
        if name in {"respawn-stale", "hard-stop"}:
            command.add_argument("--node", required=True)
            command.add_argument("--reason", required=True)
        if name == "authorize-dispatch":
            command.add_argument("--prompt", required=True)
            command.add_argument("--subagent-type", required=True)
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
    """Abort an update that only checks state or finds no change."""


def convert_state(path: Path, session: str, check: bool) -> dict[str, Any]:
    """Convert graph state under the Claude lock and keep a backup."""
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
    if not saved and (not report or (report["changed"] and not check)):
        raise ValueError("progress.json is locked, unreadable or not an object")
    if saved:
        load(path)
    trace(path, {"session_id": session}, "ok", "convert_ok", inputs, [], "convert")
    return {**report, "check": check, "backup": backup[0].name if backup else None}


def record_unit(path: Path, session: str, unit_id: str, status: str, detail: str) -> dict[str, Any]:
    """Record an independently checked work-unit decision through the Claude lock."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        if state["session_id"] != session:
            raise ValueError("session does not own this graph")
        if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
            raise ValueError("work unit requires an in-progress graph without an active wave")
        units = cast(object, state.get("work_units"))
        if not unit_id.strip() or not isinstance(units, dict):
            raise ValueError("work unit must be registered")
        unit = cast(dict[str, object], units).get(unit_id)
        if not isinstance(unit, dict):
            raise ValueError("work unit must be registered and pending")
        record = cast(dict[str, object], unit)
        if record.get("status") != "pending":
            raise ValueError("work unit must be registered and pending")
        if status not in {"done", "dropped"} or not detail.strip():
            raise ValueError("work unit decision requires a status and nonblank evidence or reason")
        record["status"] = status
        record["evidence" if status == "done" else "dropped_reason"] = detail.strip()
        output.update(unit=unit_id, status=status, revision=state["revision"])
        return state

    transition(path, update)
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


def record_proof_disposition(
    path: Path, session: str, loop_id: str, revision: int, disposition: str, reason: str
) -> dict[str, Any]:
    """Save an owner's no-proof decision under the sole Claude state lock."""
    inputs = {"session": session, "loop_id": loop_id, "revision": revision, "disposition": disposition}
    observed: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        observed.update(state)
        if state["session_id"] != session or state["loop_id"] != loop_id:
            raise ValueError("wrong owner or loop")
        if state["revision"] != revision:
            raise ValueError("stale revision")
        if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
            raise ValueError("no-proof decision requires an idle in-progress loop")
        if disposition != "none" or not reason.strip() or reason.strip().lower().startswith("none:"):
            raise ValueError("disposition must be none with a nonblank reason and no prefix")
        if path.with_name("proof.json").exists():
            raise ValueError("proof.json exists; no-proof decision is invalid")
        if state.get("proof_disposition") is not None:
            raise ValueError("proof disposition is already recorded")
        state["proof_disposition"] = f"none: {reason.strip()}"
        return state

    try:
        transition(path, update)
    except ValueError:
        trace(path, observed, "refused", "proof_disposition_refused", inputs, [], "record-proof-disposition")
        raise
    trace(path, observed, "ok", "proof_disposition_recorded", inputs, [], "record-proof-disposition")
    return {"proof_disposition": f"none: {reason.strip()}", "revision": revision}


def main() -> int:
    """Run one explicit graph operation with fail-closed CLI status."""
    args = parser().parse_args()
    try:
        if args.command == "start":
            output: object = graph_controller.start(args.state, args.session, args.loop_id, args.prompt_file)
        elif args.command == "add-unit":
            output = graph_controller.add_unit(
                args.state, args.session, args.loop_id, args.unit, args.depends_on, args.join, args.manifest
            )
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
        elif args.command == "collection":
            output = graph_recovery.collection(args.state)
        elif args.command == "recover-wave":
            output = dispatch.recover_wave(args.state, args.session, args.lease_seconds, apply=not args.report_only)
        elif args.command == "plan":
            output = dispatch.plan(args.state)
        elif args.command == "begin-wave":
            output = dispatch.begin_wave(args.state)
        elif args.command == "record-wave":
            output = dispatch.record_wave(args.state, object_value(json.loads(args.results_json), "wave report"))
        elif args.command == "record-unit":
            if (args.status == "done") != (args.evidence is not None):
                raise ValueError("done requires --evidence; dropped requires --reason")
            output = record_unit(args.state, args.session, args.unit, args.status, args.evidence or args.reason)
        elif args.command == "record-decision":
            output = decision_record.record(
                args.state,
                args.session,
                args.phase,
                args.decision,
                expected_loop_id=args.loop_id,
                expected_revision=args.revision,
                transition=transition,
                flip_condition=args.flip_condition,
                unit=args.unit,
                cite_quote=args.cite_quote,
            )
        elif args.command == "flush-decisions":
            output = decision_record.flush_pending(
                args.state,
                args.session,
                transition=transition,
                cite_quote=args.cite_quote,
            )
        elif args.command == "record-repair":
            output = record_repair(
                args.state, args.session, args.unit, args.failed_node, args.kind, args.identity, args.diagnosis
            )
        elif args.command == "record-proof-disposition":
            output = record_proof_disposition(
                args.state, args.session, args.loop_id, args.revision, args.disposition, args.reason
            )
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = native_transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "stop":
            output = record_stop(args.state, args.session, args.category, args.reason_code, args.reason)
        elif args.command == "convert":
            output = convert_state(args.state, args.session, args.check)
        elif args.command == "authorize-dispatch":
            output = dispatch.authorize_dispatch(args.state, args.session, args.prompt, args.subagent_type)
        else:
            output = dispatch.complete(args.state, args.session, args.command == "complete")
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return int(output.get("exit_code", 0)) if isinstance(output, dict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
