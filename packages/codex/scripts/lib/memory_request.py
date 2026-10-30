"""Request task learning from Muninn and verify its current result.

Submission is not a write.  A saved request ID is the only safe retry handle.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Any, cast

from scripts.lib import memory_adapter as ma

REQUEST_ID = re.compile(r"R_[0-9a-f]{32}")
KNOWLEDGE_ID = re.compile(r"K_[0-9a-f]{32}")
TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


@dataclasses.dataclass(frozen=True)
class Pending:
    """A saved Muninn request that has no verified current note yet."""

    request_id: str
    window: dict[str, Any] | None = None
    project_id: str | None = None


def _json(value: str | ma.Degraded) -> dict[str, Any] | ma.Degraded:
    if isinstance(value, ma.Degraded):
        return value
    try:
        payload: object = json.loads(value)
    except (TypeError, ValueError):
        return ma.Degraded("muninn_bad_output")
    return cast("dict[str, Any]", payload) if isinstance(payload, dict) else ma.Degraded("muninn_bad_output")


def _object(value: object) -> dict[str, Any] | None:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _array(value: object) -> list[Any] | None:
    return cast("list[Any]", value) if isinstance(value, list) else None  # type: ignore[redundant-cast]


def probe() -> ma.Degraded | None:
    """Check that Muninn supports task-scoped review requests."""
    backend = ma.backend()
    if backend != "muninn":
        return ma.Degraded("memory_backend_off" if backend == "off" else "memory_backend_invalid")
    for argv, flags in (
        (["learn", "request", "--help"], ("--session", "--task")),
        (["know", "list", "--help"], ("--task",)),
    ):
        help_text = ma.run_cli(argv, True)
        if isinstance(help_text, ma.Degraded):
            return help_text
        if any(flag not in help_text for flag in flags):
            return ma.Degraded("muninn_old_ledger")
    return None


def submit(session: str, task: str) -> Pending | ma.Degraded:
    """Submit one bounded request.  Never repeat this call after an uncertain result."""
    if not session or TASK.fullmatch(task) is None:
        return ma.Degraded("bad_record")
    down = probe()
    if down is not None:
        return down
    response = _json(ma.run_cli(["learn", "request", "--session", session, "--task", task]))
    if isinstance(response, ma.Degraded):
        return response
    scope = _object(response.get("scope"))
    window = _object(response.get("window"))
    ident = response.get("id")
    if not isinstance(ident, str) or REQUEST_ID.fullmatch(ident) is None or scope is None:
        return ma.Degraded("muninn_bad_output")
    source = _object(window.get("source")) if window is not None else None
    if (
        not isinstance(scope.get("project_id"), str)
        or scope.get("task") != task
        or window is None
        or source is None
        or not isinstance(source.get("provider"), str)
        or not isinstance(source.get("thread_id"), str)
        or type(window.get("from_line")) is not int
        or type(window.get("through_line")) is not int
        or not isinstance(window.get("boundary_hash"), str)
    ):
        return ma.Degraded("muninn_bad_output")
    return Pending(ident, window, scope["project_id"])


def inspect(
    request_id: str,
    task: str,
    kind: str,
    claim: str,
    *,
    expected_window: dict[str, Any] | None = None,
    expected_project: str | None = None,
) -> ma.Record | Pending | ma.Degraded:
    """Accept only a completed receipt and one eligible, exact current note."""
    backend = ma.backend()
    if backend != "muninn":
        return ma.Degraded("memory_backend_off" if backend == "off" else "memory_backend_invalid")
    if REQUEST_ID.fullmatch(request_id) is None or TASK.fullmatch(task) is None:
        return ma.Degraded("bad_record")
    detail = _json(ma.run_cli(["learn", "show", request_id]))
    if isinstance(detail, ma.Degraded):
        return detail
    request = _object(detail.get("request"))
    if request is None or request.get("id") != request_id:
        return ma.Degraded("muninn_bad_output")
    scope = _object(request.get("scope"))
    if scope is None or not isinstance(scope.get("project_id"), str) or scope.get("task") != task:
        return ma.Degraded("muninn_bad_output")
    if expected_project is not None and scope["project_id"] != expected_project:
        return ma.Degraded("muninn_bad_output")
    if expected_window is not None and request.get("window") != expected_window:
        return ma.Degraded("muninn_bad_output")
    if request.get("state") in {"pending", "running", "waiting"}:
        return Pending(request_id, _object(request.get("window")), scope["project_id"])
    if request.get("state") != "completed":
        return ma.Degraded("learning_request_failed")
    receipt = _object(detail.get("receipt"))
    if receipt is None or receipt.get("request_id") != request_id:
        return ma.Degraded("muninn_bad_output")
    applied = _array(receipt.get("applied"))
    if applied is None:
        return ma.Degraded("muninn_bad_output")
    listed = _json(ma.run_cli(["know", "list", "--task", task]))
    if isinstance(listed, ma.Degraded):
        return listed
    current = _array(listed.get("knowledge"))
    if current is None:
        return ma.Degraded("muninn_bad_output")
    current_ids: set[tuple[str, int]] = set()
    for value in current:
        note = _object(value)
        if note is not None and isinstance(note.get("id"), str) and type(note.get("revision")) is int:
            current_ids.add((note["id"], note["revision"]))
    matches: list[ma.Record] = []
    for value in applied:
        affected = _object(value)
        if affected is None:
            return ma.Degraded("muninn_bad_output")
        kid, revision = affected.get("knowledge_id"), affected.get("revision")
        if type(revision) is not int or revision < 1:
            return ma.Degraded("muninn_bad_output")
        if not isinstance(kid, str) or KNOWLEDGE_ID.fullmatch(kid) is None or (kid, revision) not in current_ids:
            continue
        shown = _json(ma.run_cli(["know", "show", kid]))
        if isinstance(shown, ma.Degraded):
            return shown
        body = _object(shown.get("body"))
        note_scope = _object(body.get("scope")) if body is not None else None
        if (shown.get("id"), shown.get("revision"), shown.get("state")) != (kid, revision, "active"):
            continue
        if body is None or body.get("form") != "note" or note_scope is None:
            continue
        if (body.get("kind"), body.get("content")) != (kind, claim):
            continue
        if note_scope != scope:
            continue
        sources = _array(shown.get("evidence_sources"))
        if sources is None:
            continue
        refs = [
            source["ref"]
            for value in sources
            if (source := _object(value)) is not None and isinstance(source.get("ref"), str) and source["ref"]
        ]
        if not refs:
            continue
        matches.append(
            ma.Record(
                scope="loop",
                type=kind,
                claim=claim,
                cite=refs[0],
                quote="",
                loop_id=task,
                id=kid,
            )
        )
    if len(matches) != 1:
        return ma.Degraded("learning_no_matching_record")
    return matches[0]


def decision_field(row: dict[str, Any], loop_id: str, session_id: str) -> dict[str, Any]:
    """Queue or inspect one decision, retaining its exact durable request binding."""
    claim = " ".join(f"{row['phase']}: {row['decision']}".split())
    previous = _object(row.get("muninn")) or {}
    if previous.get("state") == "unknown" and not isinstance(previous.get("request_id"), str):
        return dict(previous)
    if ma.backend() == "off":
        return {**previous, "state": "disabled", "id": previous.get("id"), "reason_code": "memory_backend_off"}
    request_id = previous.get("request_id")
    window, project = previous.get("request_window"), previous.get("project_id")
    if isinstance(request_id, str) and isinstance(window, dict) and isinstance(project, str):
        res = inspect(
            request_id,
            loop_id,
            "decision",
            claim,
            expected_window=cast("dict[str, Any]", window),
            expected_project=project,
        )
    elif isinstance(request_id, str):
        res = ma.Degraded("learning_request_unknown")
    else:
        res = submit(session_id, loop_id)
    field: dict[str, Any]
    if isinstance(res, ma.Record):
        field = {"state": "written", "id": res.id, "request_id": request_id, "reason_code": "ok"}
    elif isinstance(res, Pending):
        field = {"state": "pending", "id": None, "request_id": res.request_id, "reason_code": "learning_pending"}
    else:
        off = res.reason == "memory_backend_off"
        uncertain = (
            res.reason == "learning_request_unknown"
            or request_id is None
            and res.reason
            in {
                "muninn_error",
                "muninn_timeout",
                "muninn_bad_output",
            }
        )
        field = {
            "state": "disabled" if off else "unknown" if uncertain else "degraded",
            "id": None,
            "request_id": request_id,
            "reason_code": res.reason,
        }
    for key in ("request_window", "project_id"):
        if key in previous:
            field[key] = previous[key]
    if isinstance(res, Pending) and res.window is not None and res.project_id is not None:
        field.update(request_window=res.window, project_id=res.project_id)
    return field
