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
    ident = response.get("id")
    if not isinstance(ident, str) or REQUEST_ID.fullmatch(ident) is None or scope is None:
        return ma.Degraded("muninn_bad_output")
    if scope.get("project_id") is None or scope.get("task") != task:
        return ma.Degraded("muninn_bad_output")
    return Pending(ident)


def inspect(request_id: str, task: str, kind: str, claim: str) -> ma.Record | Pending | ma.Degraded:
    """Accept only a completed receipt and one eligible, exact current note."""
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
    if request.get("state") in {"pending", "running", "waiting"}:
        return Pending(request_id)
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
