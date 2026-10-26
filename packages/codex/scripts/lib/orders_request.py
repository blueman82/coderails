"""Stage one durable order request before Muninn can accept it."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from scripts.lib import lessons
from scripts.lib import memory_adapter as ma
from scripts.lib import memory_request as mr
from scripts.lib import orders_ledger as ol
from scripts.lib import orders_lifecycle as lifecycle


def _claim(order: dict[str, Any]) -> str:
    return " ".join(str(order["lesson"]).split())


def needs_submit(order: dict[str, Any], task: str, session: str) -> bool:
    """Reuse a request only in its original task and source session."""
    previous = order.get("muninn", {})
    digest = hashlib.sha256(_claim(order).encode()).hexdigest()
    if previous.get("claim_sha256") != digest or previous.get("task") not in (None, task):
        return True
    if previous.get("source_session") not in (None, session):
        return True
    return previous.get("state") != "unknown" and not isinstance(previous.get("request_id"), str)


def _journal(repo_dir: Path, order: dict[str, Any], session: str, task: str) -> tuple[Path, dict[str, str]]:
    binding = {
        "repo_dir": str(repo_dir.resolve()),
        "order_id": str(order["id"]),
        "session": session,
        "task": task,
        "claim_sha256": hashlib.sha256(_claim(order).encode()).hexdigest(),
    }
    key = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    return repo_dir / f"order-request-{key}.json", binding


def recover(order: dict[str, Any], repo_dir: Path, session: str, task: str) -> dict[str, Any]:
    """Use only the exact R_ ID that this process saved before its final local save."""
    if isinstance(order.get("muninn", {}).get("request_id"), str):
        return order
    path, binding = _journal(repo_dir, order, session, task)
    if not path.exists():
        return order
    saved = lifecycle.object_file(path)
    rid = saved.get("request_id")
    window, project = saved.get("request_window"), saved.get("project_id")
    if (
        {key: saved.get(key) for key in binding} != binding
        or not isinstance(rid, str)
        or not mr.REQUEST_ID.fullmatch(rid)
        or not isinstance(window, dict)
        or not isinstance(project, str)
    ):
        raise ValueError("order_state_error")
    field: dict[str, Any] = {
        **cast("dict[str, Any]", order.get("muninn", {})),
        "state": "pending",
        "id": None,
        "request_id": rid,
        "source_session": session,
        "request_window": window,
        "project_id": project,
        "task": task,
        "claim_sha256": binding["claim_sha256"],
        "reason_code": "learning_pending",
    }
    return {**order, "muninn": field}


def save_response(order: dict[str, Any], repo_dir: Path, session: str, task: str, field: dict[str, Any]) -> None:
    """Save the returned R_ ID before the order's final local publication."""
    rid = field.get("request_id")
    window, project = field.get("request_window"), field.get("project_id")
    if (
        not isinstance(rid, str)
        or not mr.REQUEST_ID.fullmatch(rid)
        or not isinstance(window, dict)
        or not isinstance(project, str)
    ):
        return
    path, binding = _journal(repo_dir, order, session, task)
    ol.save(path, {**binding, "request_id": rid, "request_window": window, "project_id": project})


def sync_order(
    order: dict[str, Any],
    session: str,
    repo_dir: Path,
    ledger: ol.Ledger,
    task: str,
    *,
    issue: bool = False,
) -> dict[str, Any]:
    """Plan a marker, inspect a saved request, or issue after the marker was saved."""
    lifecycle.check_staged_identity(repo_dir, ledger, order)
    previous = cast("dict[str, Any]", order.get("muninn", {}))
    claim = _claim(order)
    digest = hashlib.sha256(claim.encode()).hexdigest()
    same_claim = (
        previous.get("claim_sha256") == digest
        and previous.get("task") == task
        and previous.get("source_session") == session
    )
    legacy_unknown = (
        previous.get("claim_sha256") == digest
        and previous.get("state") == "unknown"
        and previous.get("task") in (None, task)
        and previous.get("source_session") is None
    )
    request_id = previous.get("request_id")
    if same_claim and isinstance(request_id, str):
        window, project = previous.get("request_window"), previous.get("project_id")
        if isinstance(window, dict) and isinstance(project, str):
            result = mr.inspect(
                request_id,
                previous.get("task", task),
                "lesson",
                claim,
                expected_window=cast("dict[str, Any]", window),
                expected_project=project,
            )
        else:
            result = ma.Degraded("learning_request_unknown")
    elif (same_claim and previous.get("state") == "unknown" or legacy_unknown) and not issue:
        return dict(previous)
    elif (
        previous.get("claim_sha256") == digest
        and isinstance(request_id, str)
        and previous.get("task") in (None, task)
        and previous.get("source_session") is None
    ):
        return {**previous, "state": "unknown", "reason_code": "learning_request_unknown"}
    elif not issue:
        return {
            "state": "unknown",
            "id": previous.get("id"),
            "request_id": None,
            "task": task,
            "source_session": session,
            "claim_sha256": digest,
            "reason_code": "learning_request_unknown",
        }
    else:
        result = mr.submit(session, task)
    field = lessons.metadata(result, previous.get("id"))
    field.update(task=task, source_session=session, claim_sha256=digest)
    if isinstance(result, mr.Pending):
        field["request_id"] = result.request_id
        if result.window is not None and result.project_id is not None:
            field.update(request_window=result.window, project_id=result.project_id)
    if isinstance(request_id, str) and same_claim:
        field["request_id"] = request_id
    if isinstance(result, ma.Degraded) and result.reason in {
        "learning_request_unknown",
        "muninn_error",
        "muninn_timeout",
        "muninn_bad_output",
    }:
        field["state"] = "unknown"
    if same_claim:
        field.update({key: previous[key] for key in ("request_window", "project_id") if key in previous})
    return field
