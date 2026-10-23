"""Native Codex graph mutations outside the pure wave transitions."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_identity import GraphError
from graph_io import load, locked, write

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import decision_record  # noqa: E402


def record_unit(path: Path, session: str, unit_id: str, status: str, detail: str) -> dict[str, Any]:
    """Record an independently checked work-unit decision under the state lock."""
    with locked(path):
        state = load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
            raise GraphError("work unit requires an in-progress graph without an active wave")
        units = cast(object, state.get("work_units"))
        if not isinstance(cast(object, unit_id), str) or not unit_id.strip() or not isinstance(units, dict):
            raise GraphError("work unit must be registered")
        unit = cast(dict[str, object], units).get(unit_id)
        if not isinstance(unit, dict):
            raise GraphError("work unit must be registered and pending")
        record = cast(dict[str, object], unit)
        if record.get("status") != "pending":
            raise GraphError("work unit must be registered and pending")
        if status not in {"done", "dropped"} or not isinstance(cast(object, detail), str) or not detail.strip():
            raise GraphError("work unit decision requires a status and nonblank evidence or reason")
        record["status"] = status
        record["evidence" if status == "done" else "dropped_reason"] = detail.strip()
        graph_semantics.validate(state)
        write(path, state)
        return {"unit": unit_id, "status": status, "revision": state["revision"]}


def decision_transition(path: Path, fn: Any) -> dict[str, Any]:  # noqa: ANN401
    """Apply one decision transform through Codex's native graph lock."""
    with locked(path):
        proposed = fn(load(path))
        graph_semantics.validate(proposed)
        write(path, proposed)
        return cast(dict[str, Any], proposed)


def record_decision(args: Any) -> dict[str, Any]:  # noqa: ANN401
    """Record and sync one typed decision using the provider lock."""
    return decision_record.record(
        args.state,
        args.session,
        args.phase,
        args.decision,
        transition=decision_transition,
        flip_condition=args.flip_condition,
        unit=args.unit,
        cite_quote=args.cite_quote,
    )


def flush_decisions(args: Any) -> dict[str, Any]:  # noqa: ANN401
    """Retry pending decision syncs using the provider lock."""
    return decision_record.flush_pending(
        args.state,
        args.session,
        transition=decision_transition,
        cite_quote=args.cite_quote,
    )
