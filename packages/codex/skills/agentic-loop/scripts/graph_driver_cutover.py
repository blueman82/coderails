"""Codex-owned one-way driver cutover under the existing graph lock."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import graph_contract
import graph_convert
import graph_dispatch
import graph_driver_mode
import graph_semantics
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError
from graph_io import load, locked, write
from graph_recovery import trace

COMMANDS = frozenset({"cutover-driver", "begin-driver-wave", "record-driver-wave", "authorize-driver"})


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
    authorize = add_parser("authorize-driver")
    authorize.add_argument("state", type=Path)
    for field in ("session", "dispatch-id", "role", "driver-run-id"):
        authorize.add_argument(f"--{field}", required=True)
    authorize.add_argument("--prompt-file", required=True, type=Path)


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Route one driver command to its locked provider operation."""
    if args.command == "cutover-driver":
        return cutover_driver(args.state, args.session)
    if args.command == "begin-driver-wave":
        return graph_dispatch.begin_driver_wave(args.state)
    if args.command == "record-driver-wave":
        return graph_dispatch.record_driver_wave(args.state, args.results_json)
    return graph_dispatch.authorize_driver(
        args.state, args.session, args.dispatch_id, args.prompt_file, args.role, args.driver_run_id
    )
