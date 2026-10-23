"""Claude-owned locked entrypoints for driver waves and authorization."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import graph_driver_dispatch
import graph_driver_evidence

from .graph_dispatch import validate_dispatch_evals
from .graph_evidence import object_value
from .graph_executor import ROOT, graph_semantics, transition


def record_wave(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Record a sealed driver wave through the Claude graph lock."""
    saved = transition(
        path,
        lambda state: object_value(graph_driver_evidence.apply_record(path, state, report)["state"], "driver state"),
    )
    return {"revision": saved["revision"], "ready": graph_semantics.ready(saved)}


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
