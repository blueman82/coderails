"""Codex-owned one-way driver cutover under the existing graph lock."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

import graph_contract
import graph_convert
import graph_driver_mode
import graph_semantics
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError
from graph_io import load, locked, write
from graph_recovery import trace


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
