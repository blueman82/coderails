"""Apply native completion evidence and independent work-unit gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_evidence import validate_completion_evidence, validate_worker_evidence
from graph_identity import GraphError
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import object_value as _object
from graph_io import write as _write
from graph_recovery import traced_refusal


def validate_work_units(state: dict[str, Any]) -> None:
    """Require each optional implementation unit to be done or reasonedly dropped."""
    units = state.get("work_units")
    if units is None:
        return
    if not isinstance(units, dict):
        raise GraphError("work_units must be an object")
    for unit_id, unit in cast(dict[object, object], units).items():
        if not isinstance(unit_id, str) or not unit_id.strip() or not isinstance(unit, dict):
            raise GraphError("work_units entries must be named objects")
        unit = cast(dict[str, object], unit)
        if unit.get("status") == "done":
            continue
        reason = unit.get("dropped_reason")
        if unit.get("status") == "dropped" and isinstance(reason, str) and reason.strip():
            continue
        raise GraphError(f"work unit {unit_id} is unfinished or malformed")


def _validate_completion(
    state: dict[str, Any],
    session: str,
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> None:
    if state["session_id"] != session:
        raise GraphError("session does not own this loop")
    eligibility = graph_semantics.can_complete(state)
    if not eligibility["eligible"]:
        raise GraphError("cannot complete graph: " + ", ".join(eligibility["blockers"]))
    validate_work_units(state)
    validate_worker_evidence(state)
    validate_completion_evidence(state, revision, evals_path, proof_path, retro_path, transcript_path)


def complete(
    path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path, transcript_path: Path | None
) -> dict[str, Any]:
    """Mark the graph complete only after all native gates pass."""
    with _locked(path):
        state = _load(path)
        if state["status"] == "complete":
            raise GraphError("graph is already complete")
        revision = state["revision"]
        with traced_refusal(path, state, "complete", session):
            _validate_completion(state, session, revision, evals_path, proof_path, retro_path, transcript_path)
        state["status"] = "complete"
        state["revision"] += 1
        state["completion"] = {"revision": revision}
        _write(path, state)
        return {"status": "complete", "loop_id": state["loop_id"], "revision": state["revision"]}


def verify_completion(
    path: Path, session: str, evals_path: Path, proof_path: Path, retro_path: Path, transcript_path: Path | None
) -> dict[str, Any]:
    """Revalidate the recorded completion against live native evidence."""
    state = _load(path)
    completion = _object(state.get("completion"), "completion")
    revision = completion.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int):
        raise GraphError("graph completion revision must be an integer")
    if state["status"] != "complete" or revision != state["revision"] - 1:
        raise GraphError("graph has no valid completion record")
    with traced_refusal(path, state, "verify-completion", session):
        _validate_completion(state, session, revision, evals_path, proof_path, retro_path, transcript_path)
    return {"status": "complete", "loop_id": state["loop_id"], "revision": state["revision"]}
