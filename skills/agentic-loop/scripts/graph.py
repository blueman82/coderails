#!/usr/bin/env python3
"""Operate the native Claude schema-v3 graph through its provider-owned adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_controller, graph_recovery
from hooks.scripts.lib import graph_dispatch as dispatch
from hooks.scripts.lib.graph_evidence import object_value
from hooks.scripts.lib.graph_executor import graph_semantics, load, transition


def parser() -> argparse.ArgumentParser:
    """Expose only current semantic operations and native completion checks."""
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in (
        "start",
        "add-unit",
        "inspect",
        "summarize",
        "recover-wave",
        "plan",
        "begin-wave",
        "record-wave",
        "record-unit",
        "respawn-stale",
        "hard-stop",
        "authorize-dispatch",
        "complete",
        "verify-completion",
    ):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
        if name == "record-wave":
            command.add_argument("results_json")
        if name == "record-unit":
            command.add_argument("--unit", required=True)
            command.add_argument("--status", required=True, choices=("done", "dropped"))
            detail = command.add_mutually_exclusive_group(required=True)
            detail.add_argument("--evidence")
            detail.add_argument("--reason")
        if name in {"start", "add-unit"}:
            command.add_argument("--session", required=True)
            command.add_argument("--loop-id", required=True)
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
        if name in {
            "respawn-stale",
            "hard-stop",
            "authorize-dispatch",
            "record-unit",
            "complete",
            "verify-completion",
            "recover-wave",
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
        elif args.command == "inspect":
            state = load(args.state)
            output = {
                "session_id": state["session_id"],
                "loop_id": state["loop_id"],
                **graph_semantics.inspect(state),
            }
        elif args.command == "summarize":
            output = graph_recovery.summarize(load(args.state))
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
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = native_transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "authorize-dispatch":
            output = dispatch.authorize_dispatch(args.state, args.session, args.prompt, args.subagent_type)
        else:
            output = dispatch.complete(args.state, args.session, args.command == "complete")
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
