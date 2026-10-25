"""Native Codex graph mutations outside the pure wave transitions."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

import graph_convert
import graph_semantics
import worker_status
from graph_identity import GraphError
from graph_io import load, locked, write
from graph_recovery import trace

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
        expected_loop_id=args.loop_id,
        expected_revision=args.revision,
        transition=decision_transition,
        flip_condition=args.flip_condition,
        unit=args.unit,
        cite_quote=args.cite_quote,
        chosen=args.chosen,
        worker_status_seq=args.worker_status_seq,
        human_answer=args.human_answer,
        status_resolver=worker_status.resolve_pending,
    )


def flush_decisions(args: Any) -> dict[str, Any]:  # noqa: ANN401
    """Retry pending decision syncs using the provider lock."""
    return decision_record.flush_pending(
        args.state,
        args.session,
        transition=decision_transition,
        cite_quote=args.cite_quote,
    )


def convert_state(path: Path, session: str, check: bool) -> dict[str, Any]:
    """Convert progress.json under the Codex lock and keep a backup."""
    inputs: dict[str, Any] = {"session": session, "check": check}
    backup: Path | None = None
    report: dict[str, Any] = {}
    try:
        with locked(path):
            try:
                raw: object = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise GraphError(f"cannot read state: {error}") from error
            converted, report = graph_convert.convert(raw, session)
            if report["changed"] and not check:
                try:
                    graph_semantics.validate(converted)
                except ValueError as error:
                    raise graph_convert.ConvertRefusedError("invalid_result", str(error)) from error
                backup = graph_convert.write_backup(path)
                write(path, converted)
                load(path)
    except graph_convert.ConvertRefusedError as error:
        trace(path, {"session_id": session}, "refused", f"convert_refused_{error.code}", inputs, [], "convert")
        raise GraphError(str(error)) from error
    trace(path, {"session_id": session}, "ok", "convert_ok", inputs, [], "convert")
    return {**report, "check": check, "backup": backup.name if backup else None}
