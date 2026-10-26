"""Claude-owned locked entrypoints for driver waves and authorization."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import graph_driver_control
import graph_driver_controller
import graph_driver_dispatch
import graph_driver_evidence
import graph_repair
import worker_status

from .graph_dispatch import validate_dispatch_evals
from .graph_evidence import object_value
from .graph_executor import ROOT, graph_semantics, load, transition
from .graph_stops import record_stop


def add_arguments(name: str, command: argparse.ArgumentParser) -> None:
    """Add the driver-only Claude CLI arguments."""
    command.add_argument("--session", required=True)
    if name == "append-unit-scope-note":
        for field in ("loop-id", "revision", "unit", "expected-scope-sha256", "note", "reason"):
            command.add_argument(f"--{field}", required=True, type=int if field == "revision" else str)
    elif name == "assign-unit-scope":
        command.add_argument("--unit", required=True)
        command.add_argument("--scope", required=True)
    elif name == "drive":
        command.add_argument("--wait-seconds", type=float, default=30)
        checkout = command.add_mutually_exclusive_group()
        checkout.add_argument("--checkout", type=Path)
        checkout.add_argument("--checkout-map", type=Path)
    else:
        command.add_argument("--node", required=True)
        command.add_argument("--result-file", required=True, type=Path)


def record_wave(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Record a sealed driver wave through the Claude graph lock."""

    def update(state: dict[str, Any]) -> dict[str, Any]:
        result = graph_driver_evidence.apply_record(path, state, report, worker_status.prepare)
        proposed = object_value(result["state"], "driver state")
        statuses, reports = result["statuses"], result["reports"]
        worker_status.retain_decision_slot(proposed, statuses)
        graph_repair.apply_failed_gates(result, result["core_results"])
        worker_status.record_into(proposed, report["wave_id"], statuses, reports)
        if statuses:
            category, code, reason = worker_status.stop_for(statuses)
            proposed = object_value(
                record_stop(proposed, state["session_id"], category, code, reason)["state"], "stops"
            )
        return proposed

    saved = transition(path, update)
    return {"revision": saved["revision"], "ready": graph_semantics.ready(saved)}


def record_control(path: Path, session: str, node_id: str, result_file: Path) -> dict[str, Any]:
    """Stage a root-owned result bound to the current wave without rewriting progress."""
    return graph_driver_control.stage(path, load(path), session, node_id, result_file)


def assign_scope(path: Path, session: str, unit: str, scope: str) -> dict[str, Any]:
    """Save one pending unit assignment through the Claude graph lock."""
    saved = transition(path, lambda state: graph_driver_controller.assign_scope(state, session, unit, scope))
    return {"unit": unit, "scope": saved["work_units"][unit]["scope"], "revision": saved["revision"]}


def append_scope_note(
    path: Path,
    session: str,
    loop_id: str,
    revision: int,
    unit: str,
    expected_scope_sha256: str,
    note: str,
    reason: str,
) -> dict[str, Any]:
    """Save a scoped note under the Claude graph lock."""
    saved = transition(
        path,
        lambda state: graph_driver_control.append_scope_note(
            state, session, loop_id, revision, unit, expected_scope_sha256, note, reason
        ),
    )
    return {
        "unit": unit,
        "revision": saved["revision"],
        "scope_sha256": saved["work_units"][unit]["scope_notes"][-1]["new_sha256"],
    }


def append_scope_note_command(args: argparse.Namespace) -> dict[str, Any]:
    """Pass parsed Claude CLI fields to the locked transition."""
    return append_scope_note(
        args.state,
        args.session,
        args.loop_id,
        args.revision,
        args.unit,
        args.expected_scope_sha256,
        args.note,
        args.reason,
    )


def run_scope_command(args: argparse.Namespace) -> dict[str, Any]:
    """Apply the selected locked unit-scope command."""
    if args.command == "assign-unit-scope":
        return assign_scope(args.state, args.session, args.unit, args.scope)
    return append_scope_note_command(args)


def begin_wave(path: Path) -> dict[str, Any]:
    """Open the full ready set under the Claude graph lock and frozen eval gate."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        for node_id in graph_semantics.ready(state):
            validate_dispatch_evals(path, state, node_id)
        report = graph_driver_dispatch.begin_wave(state, path, ROOT / "scripts/push.py")
        output.update(report["wave"])
        output["dispatches"] = report["dispatches"]
        return object_value(report["state"], "driver wave state")

    transition(path, update)
    return output


def authorize(
    path: Path, session: str, dispatch_id: str, prompt_file: Path, role: str, driver_run_id: str
) -> dict[str, Any]:
    """Consume one Claude driver slot under the graph lock."""

    def update(state: dict[str, Any]) -> dict[str, Any]:
        proposed = graph_driver_dispatch.authorize(
            state, path, ROOT / "scripts/push.py", session, dispatch_id, prompt_file, role, driver_run_id
        )
        node_id = proposed["graph"]["dispatches"][dispatch_id]["node_id"]
        validate_dispatch_evals(path, state, node_id, worker=True)
        return proposed

    transition(path, update)
    return {"dispatch_id": dispatch_id, "driver_run_id": driver_run_id}
