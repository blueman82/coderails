"""Locked graph record writers, separate from loop and unit registration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from .graph_executor import graph_repair, transition
from .graph_recovery import trace


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
