"""Codex-owned one-way driver cutover under the existing graph lock."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast

import graph_contract
import graph_convert
import graph_dispatch
import graph_driver_codex
import graph_driver_controller
import graph_driver_mode
import graph_semantics
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError
from graph_io import load, locked, write
from graph_recovery import trace

COMMANDS = frozenset(
    {"cutover-driver", "begin-driver-wave", "record-driver-wave", "record-driver-control", "authorize-driver", "drive"}
)


class ScopeParsers(Protocol):
    """The parser operation used by both scope commands."""

    def add_parser(self, name: str) -> argparse.ArgumentParser:
        """Add a subcommand parser."""
        ...


def add_scope_arguments(commands: ScopeParsers) -> None:
    """Add both unit scope commands to the Codex CLI."""
    assignment = commands.add_parser("assign-unit-scope")
    assignment.add_argument("state", type=Path)
    for field in ("session", "unit", "scope"):
        assignment.add_argument(f"--{field}", required=True)
    scope_note = commands.add_parser("append-unit-scope-note")
    scope_note.add_argument("state", type=Path)
    for field in ("session", "loop-id", "revision", "unit", "expected-scope-sha256", "note", "reason"):
        scope_note.add_argument(f"--{field}", required=True, type=int if field == "revision" else str)


def run_scope_command(args: argparse.Namespace) -> dict[str, Any]:
    """Apply the selected locked unit-scope command."""
    if args.command == "assign-unit-scope":
        return graph_dispatch.assign_scope(args.state, args.session, args.unit, args.scope)
    return graph_dispatch.append_scope_note(
        args.state,
        args.session,
        args.loop_id,
        args.revision,
        args.unit,
        args.expected_scope_sha256,
        args.note,
        args.reason,
    )


def cutover_driver(path: Path, session: str) -> dict[str, Any]:
    """Verify retained native history, back it up, then mark driver-only future waves."""
    with locked(path):
        state = load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        try:
            graph_contract.require_converted(state)
            result = graph_driver_mode.cutover(state, hashlib.sha256(path.read_bytes()).hexdigest())
            graph = state["graph"]
            fresh = not graph.get("wave_history") and all(
                node["status"] == "pending" and node["retry"]["attempts"] == 0 and not node["evidence"]
                for node in graph["nodes"].values()
            )
            if not fresh:
                validate_worker_evidence(state, require_complete=False)
            proposed = cast(dict[str, Any], result["state"])
            graph_semantics.validate(proposed)
            graph_convert.write_backup(path, ".pre-driver")
        except ValueError as error:
            raise GraphError(str(error)) from error
        write(path, proposed)
        trace(path, proposed, "ok", "driver_cutover", {}, [], "cutover-driver")
        return {"revision": proposed["revision"], "driver_from_revision": result["driver_from_revision"]}


def add_parsers(add_parser: Callable[[str], argparse.ArgumentParser]) -> None:
    """Register driver-only graph commands with the parent CLI."""
    cutover = add_parser("cutover-driver")
    cutover.add_argument("state", type=Path)
    cutover.add_argument("--session", required=True)
    for name in ("begin-driver-wave", "record-driver-wave"):
        command = add_parser(name)
        command.add_argument("state", type=Path)
        if name == "record-driver-wave":
            command.add_argument("results_json")
    control = add_parser("record-driver-control")
    control.add_argument("state", type=Path)
    control.add_argument("--session", required=True)
    control.add_argument("--node", required=True)
    control.add_argument("--result-file", required=True, type=Path)
    authorize = add_parser("authorize-driver")
    authorize.add_argument("state", type=Path)
    for field in ("session", "dispatch-id", "role", "driver-run-id"):
        authorize.add_argument(f"--{field}", required=True)
    authorize.add_argument("--prompt-file", required=True, type=Path)
    drive = add_parser("drive")
    drive.add_argument("state", type=Path)
    drive.add_argument("--session", required=True)
    drive.add_argument("--wait-seconds", type=float, default=30)
    checkout = drive.add_mutually_exclusive_group()
    checkout.add_argument("--checkout", type=Path)
    checkout.add_argument("--checkout-map", type=Path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Route one driver command to its locked provider operation."""
    if args.command == "cutover-driver":
        return cutover_driver(args.state, args.session)
    if args.command == "begin-driver-wave":
        return graph_dispatch.begin_driver_wave(args.state)
    if args.command == "drive":
        try:
            checkouts = graph_driver_controller.select_checkouts(args.checkout, args.checkout_map)
            return graph_driver_controller.drive_wave(
                args.state,
                args.session,
                Path(__file__).with_name("graph.py"),
                checkouts,
                "codex",
                lambda prompt, record: graph_driver_codex.command(
                    prompt,
                    graph_driver_controller.checkout_for(checkouts, record["node_id"]),
                    role=record["contract"]["role"],
                    model_role=record["contract"]["model_role"],
                ),
                graph_driver_codex.result,
                wait_seconds=args.wait_seconds,
            )
        except (ValueError, OSError, TypeError, KeyError) as error:
            code = (
                "driver_prompt_digest_mismatch"
                if str(error) == "driver prompt changed after authorization"
                else "driver_launch_refused"
            )
            trace(args.state, {"session_id": args.session}, "refused", code, {}, [], "drive")
            raise GraphError(str(error)) from error
    if args.command == "record-driver-wave":
        return graph_dispatch.record_driver_wave(args.state, args.results_json)
    if args.command == "record-driver-control":
        return graph_dispatch.record_driver_control(args.state, args.session, args.node, args.result_file)
    return graph_dispatch.authorize_driver(
        args.state, args.session, args.dispatch_id, args.prompt_file, args.role, args.driver_run_id
    )
