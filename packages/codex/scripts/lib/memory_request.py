"""Request task learning from Muninn and verify its current result.

Submission is not a write.  A saved request ID is the only safe retry handle.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from typing import Any, cast

from scripts.lib import memory_adapter as ma
from scripts.lib import memory_current as current
from scripts.lib import memory_support as support

Note = current.Note
MAX_REQUESTS = 100

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


def submit(session: object, task: str) -> Pending | ma.Degraded:
    """Submit one bounded request.  Never repeat this call after an uncertain result."""
    if not isinstance(session, str) or not session or TASK.fullmatch(task) is None:
        return ma.Degraded("bad_record")
    down = probe()
    if down is not None:
        return down
    mapped = current.project()
    if isinstance(mapped, ma.Degraded):
        return mapped
    response = _json(ma.run_cli(["learn", "request", "--session", session, "--task", task]))
    if isinstance(response, ma.Degraded):
        return ma.Degraded("learning_request_unknown", response.reason)
    ident = response.get("id")
    if not isinstance(ident, str) or REQUEST_ID.fullmatch(ident) is None:
        return ma.Degraded("learning_request_unknown", "muninn_bad_output")
    request = _request({"request": response}, ident, task, mapped)
    if isinstance(request, ma.Degraded):
        return ma.Degraded("learning_request_unknown", request.reason)
    return Pending(ident, request["window"], request["scope"]["project_id"])


def _request(
    detail: dict[str, Any], request_id: str, task: str, project: str, window: dict[str, Any] | None = None
) -> dict[str, Any] | ma.Degraded:
    request = _object(detail.get("request"))
    required = {
        "schema_version",
        "id",
        "window",
        "scope",
        "policy_digest",
        "state",
        "current_attempt_id",
        "created_at",
        "retry_at",
        "accepted",
    }
    if (
        request is None
        or not required <= request.keys()
        or type(request.get("schema_version")) is not int
        or request["schema_version"] != 1
        or type(request.get("accepted")) is not bool
        or not support.seconds(request.get("created_at"))
        or request.get("retry_at") is not None
        and not support.seconds(request["retry_at"])
        or not isinstance(request.get("policy_digest"), str)
        or support.DIGEST.fullmatch(request["policy_digest"]) is None
        or request.get("current_attempt_id") is not None
        and (
            not isinstance(request["current_attempt_id"], str)
            or re.fullmatch(r"A_[0-9a-f]{32}", request["current_attempt_id"]) is None
        )
    ):
        return ma.Degraded("muninn_bad_output")
    if (
        request.get("id") != request_id
        or request.get("scope") != {"project_id": project, "task": task}
        or window is not None
        and request.get("window") != window
    ):
        return ma.Degraded("learning_request_mismatch")
    actual = _object(request.get("window"))
    source = _object(actual.get("source")) if actual is not None else None
    if (
        actual is None
        or source is None
        or type(actual.get("from_line")) is not int
        or type(actual.get("through_line")) is not int
        or not 1 <= actual["from_line"] <= actual["through_line"]
        or not isinstance(actual.get("boundary_hash"), str)
        or support.DIGEST.fullmatch(actual["boundary_hash"]) is None
        or source.get("provider") not in {"claude", "codex", "cursor"}
        or not isinstance(source.get("thread_id"), str)
        or not source["thread_id"]
    ):
        return ma.Degraded("muninn_bad_output")
    return request


def _receipt(detail: dict[str, Any], request: dict[str, Any]) -> list[dict[str, Any]] | Pending | ma.Degraded:
    ident = request["id"]
    if request.get("state") in {"pending", "running", "waiting"}:
        return Pending(ident, request["window"], request["scope"]["project_id"])
    if request.get("state") != "completed":
        return ma.Degraded("learning_request_failed")
    receipt = _object(detail.get("receipt"))
    if receipt is None:
        return ma.Degraded("learning_receipt_unavailable")
    required = {
        "schema_version",
        "request_id",
        "attempt_id",
        "applied",
        "unresolved_ids",
        "committed_at",
        "outcome",
        "no_change_reason",
    }
    if (
        not required <= receipt.keys()
        or type(receipt.get("schema_version")) is not int
        or receipt["schema_version"] != 1
        or not isinstance(receipt.get("attempt_id"), str)
        or re.fullmatch(r"A_[0-9a-f]{32}", receipt["attempt_id"]) is None
        or request.get("current_attempt_id") not in (None, receipt["attempt_id"])
        or not support.seconds(receipt.get("committed_at"))
        or not isinstance(receipt.get("unresolved_ids"), list)
        or any(
            not isinstance(item, str) or re.fullmatch(r"U_[0-9a-f]{32}", item) is None
            for item in cast("list[object]", receipt["unresolved_ids"])
        )
    ):
        return ma.Degraded("muninn_bad_output")
    if receipt.get("request_id") != ident:
        return ma.Degraded("learning_request_mismatch")
    applied = support.objects(receipt.get("applied"))
    if applied is None:
        return ma.Degraded("muninn_bad_output")
    if receipt.get("outcome") == "no_change":
        return (
            ma.Degraded("learning_no_change")
            if not applied and not receipt["unresolved_ids"]
            else ma.Degraded("muninn_bad_output")
        )
    if receipt.get("no_change_reason") is not None:
        return ma.Degraded("muninn_bad_output")
    if receipt.get("outcome") not in {"completed", "completed_unresolved"}:
        return ma.Degraded("muninn_bad_output")
    if any(
        not isinstance(row.get("knowledge_id"), str)
        or KNOWLEDGE_ID.fullmatch(row["knowledge_id"]) is None
        or type(row.get("revision")) is not int
        or row["revision"] < 1
        for row in applied
    ):
        return ma.Degraded("muninn_bad_output")
    return applied


def inspect(
    request_id: str,
    task: str,
    kind: str,
    claim: str,
    *,
    expected_window: dict[str, Any] | None = None,
    expected_project: str | None = None,
    details: dict[str, dict[str, Any]] | None = None,
) -> Note | Pending | ma.Degraded:
    """Accept one exact receipt-bound current Note after checking every support."""
    backend = ma.backend()
    if backend != "muninn":
        return ma.Degraded("memory_backend_off" if backend == "off" else "memory_backend_invalid")
    if REQUEST_ID.fullmatch(request_id) is None or TASK.fullmatch(task) is None:
        return ma.Degraded("bad_record")
    mapped = current.project()
    if isinstance(mapped, ma.Degraded):
        return mapped
    if expected_project is None or expected_window is None or mapped != expected_project:
        return ma.Degraded("learning_request_mismatch")
    deadline = time.monotonic() + 30
    detail = support.read(["learn", "show", request_id], deadline=deadline)
    if isinstance(detail, ma.Degraded):
        return detail
    if details is not None:
        details[request_id] = detail
    request = _request(detail, request_id, task, expected_project, expected_window)
    if isinstance(request, ma.Degraded):
        return request
    applied = _receipt(detail, request)
    if not isinstance(applied, list):
        return applied
    listed = current.current(task, kind, expected_project)
    if isinstance(listed, ma.Degraded):
        return listed
    bound = [
        note
        for affected in applied
        for note in listed
        if (note.get("id"), note.get("revision")) == (affected["knowledge_id"], affected["revision"])
    ]
    matching = [note for note in bound if (_object(note.get("body")) or {}).get("content") == claim]
    if not matching and any((_object(note.get("body")) or {}).get("form") == "guide" for note in bound):
        return ma.Degraded("learning_form_unsupported")
    if len(matching) != 1:
        return ma.Degraded("learning_no_matching_record")
    return current.read(matching[0], detail, request_id, request["scope"], request["window"], deadline=deadline)


def task_notes(
    task: str,
    kind: str,
    *,
    details: dict[str, dict[str, Any]] | None = None,
    exclude: set[str] | None = None,
    refusals: list[str] | None = None,
) -> list[Note] | ma.Degraded:
    """Read extra task Notes by exact receipt joins, using retained request details first.

    Public learn list exposes metadata without task/project filtering or pagination.
    Bound its completed-request scan and filter before reading any request detail.
    Foreign metadata is neither retained nor included in diagnostics.
    """
    if ma.backend() != "muninn":
        return ma.Degraded("memory_backend_off" if ma.backend() == "off" else "memory_backend_invalid")
    project = current.project()
    if isinstance(project, ma.Degraded):
        return project
    deadline = time.monotonic() + 30
    listed = current.current(task, kind, project)
    if isinstance(listed, ma.Degraded):
        return listed
    notes = [row for row in listed if row.get("id") not in (exclude or set())]
    if not notes:
        return []
    known = dict(details or {})
    joined: list[tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]] = []
    for rid, detail in known.items():
        request = _request(detail, rid, task, project)
        if isinstance(request, ma.Degraded):
            continue
        affected = _receipt(detail, request)
        if isinstance(affected, list):
            joined.append((detail, request, affected))
    covered = {(item["knowledge_id"], item["revision"]) for _, _, applied in joined for item in applied}
    if any((note.get("id"), note.get("revision")) not in covered for note in notes):
        fetched = support.read(["learn", "list", "--state", "completed"], deadline=deadline)
        if isinstance(fetched, ma.Degraded):
            return fetched
        rows = support.objects(fetched.get("requests"))
        if rows is None:
            return ma.Degraded("muninn_bad_output")
        if len(rows) > MAX_REQUESTS:
            return ma.Degraded("learning_read_limit")
        eligible = [row for row in rows if row.get("scope") == {"project_id": project, "task": task}]
        for row in eligible:
            discovered = row.get("id")
            if not isinstance(discovered, str) or REQUEST_ID.fullmatch(discovered) is None:
                return ma.Degraded("muninn_bad_output")
            if discovered in known:
                continue
            fetched_detail = support.read(["learn", "show", discovered], deadline=deadline)
            if isinstance(fetched_detail, ma.Degraded):
                return fetched_detail
            checked = _request(fetched_detail, discovered, task, project, _object(row.get("window")))
            if isinstance(checked, ma.Degraded):
                return checked
            affected = _receipt(fetched_detail, checked)
            if isinstance(affected, list):
                joined.append((fetched_detail, checked, affected))
    result: list[Note] = []
    for note in notes:
        matches = [
            (detail, request)
            for detail, request, applied in joined
            if any(
                (item["knowledge_id"], item["revision"]) == (note.get("id"), note.get("revision")) for item in applied
            )
        ]
        record: Note | ma.Degraded
        if len(matches) != 1:
            record = ma.Degraded("learning_selection_unavailable" if not matches else "learning_record_ambiguous")
        else:
            detail, request = matches[0]
            record = current.read(note, detail, request["id"], request["scope"], request["window"], deadline=deadline)
        if isinstance(record, ma.Degraded):
            if refusals is None:
                return record
            refusals.append(record.reason)
            continue
        result.append(record)
    return result


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
    if isinstance(res, Note):
        field = {"state": "written", "id": res.id, "request_id": request_id, "reason_code": "ok", **res.metadata()}
    elif isinstance(res, Pending):
        field = {"state": "pending", "id": None, "request_id": res.request_id, "reason_code": "learning_pending"}
    else:
        if (
            res.reason == "muninn_absent"
            and previous.get("state") in {"syncing", "degraded"}
            and not previous.keys() - {"state", "id", "request_id", "reason_code"}
            and previous.get("id") is request_id is None
        ):
            return {"state": "degraded", "id": None, "reason_code": res.reason}
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
