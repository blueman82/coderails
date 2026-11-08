"""Read current cited lessons before a graph lock is acquired."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

BASE_FIELDS = {"id", "text", "cited", "cite", "quote", "muninn_id", "scope"}
NOTE_FIELDS = {
    "revision",
    "request_id",
    "body",
    "expiry",
    "supports",
    "privacy_classification",
    "privacy_checks",
    "use_allowed",
    "use_reason",
}
PRIVACY_CHECKS = {
    "project_task",
    "live_primary_source",
    "physical_hash",
    "unredacted",
    "owner_prompt",
    "selected_quote",
}


def _strings(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(cast(list[object], value))
        and all(isinstance(item, str) and bool(item.strip()) for item in cast(list[object], value))
    )


def _evidence_ids(value: object) -> bool:
    if not _strings(value):
        return False
    refs = cast(list[str], value)
    return (
        len(refs) <= 100
        and len(set(refs)) == len(refs)
        and all(re.fullmatch(r"E_[0-9a-f]{32}", ref) is not None for ref in refs)
    )


def _selection(item: dict[str, Any]) -> bool:
    original, selected = item.get("original_locator"), item.get("selector")
    if not isinstance(original, dict) or not isinstance(selected, dict):
        return False
    original, selected = cast(dict[str, Any], original), cast(dict[str, Any], selected)
    if original.get("kind") == "jsonl":
        if (
            not isinstance(original.get("path"), str)
            or not original["path"]
            or type(original.get("byte_offset")) is not int
            or original["byte_offset"] < 0
            or type(original.get("byte_length")) is not int
            or original["byte_length"] < 1
        ):
            return False
    elif original.get("kind") != "cursor_db" or any(
        not isinstance(original.get(key), str) or not original[key]
        for key in ("database", "conversation_id", "record_key")
    ):
        return False
    if not {"json_pointer", "start", "end"} <= selected.keys():
        return False
    pointer, start, end = (selected[key] for key in ("json_pointer", "start", "end"))
    if not isinstance(pointer, str) or pointer and not pointer.startswith("/"):
        return False
    if any("~" in part.replace("~0", "").replace("~1", "") for part in pointer.split("/")[1:]):
        return False
    if not (start is None and end is None or type(start) is int and type(end) is int and 0 <= start <= end):
        return False
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    return item.get("selector_digest") == digest.hexdigest()


def _support(value: object, body_scope: dict[str, Any]) -> bool:
    if not isinstance(value, dict):
        return False
    item = cast(dict[str, Any], value)
    return (
        all(isinstance(item.get(key), str) and bool(item[key].strip()) for key in ("id", "ref", "quote", "excerpt"))
        and re.fullmatch(r"E_[0-9a-f]{32}", item["id"]) is not None
        and item["quote"] == item["excerpt"]
        and all(type(item.get(key)) is int and item[key] > 0 for key in ("line", "part"))
        and isinstance(item.get("scope"), dict)
        and item["scope"].get("project_id") == body_scope["project_id"]
        and item["scope"].get("task") in (None, body_scope["task"])
        and "session_root" in item
        and all(isinstance(item.get(key), str) and bool(item[key]) for key in ("provider", "thread_id"))
        and all(
            isinstance(item.get(key), str) and bool(item[key].strip())
            for key in ("source_version", "projection_version")
        )
        and item["ref"] == f"{item['provider']}:{item['thread_id']}:{item['line']}.{item['part']}"
        and _selection(item)
        and all(
            isinstance(item.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", item[key]) is not None
            for key in ("line_sha256", "selector_digest")
        )
        and type(item.get("selected_at")) in (int, float)
        and math.isfinite(item["selected_at"])
        and item["selected_at"] >= 0
        and (item.get("state"), item.get("authority"), item.get("evidence_type"))
        == ("live", "direct_owner", "owner_statement")
    )


def _metadata(row: dict[str, Any]) -> bool:
    body, expiry, supports = row["body"], row["expiry"], row["supports"]
    if not isinstance(body, dict) or not isinstance(supports, list) or not supports:
        return False
    body = cast(dict[str, Any], body)
    supports = cast(list[object], supports)
    scope = body.get("scope")
    if not isinstance(scope, dict):
        return False
    scope = cast(dict[str, Any], scope)
    if (
        any(not isinstance(scope.get(key), str) or not scope[key].strip() for key in ("project_id", "task"))
        or body.get("form") != "note"
        or body.get("kind") != "lesson"
        or not isinstance(body.get("content"), str)
        or body["content"] != row["text"]
        or not isinstance(body.get("reason"), str)
        or not body["reason"].strip()
        or body.get("conditions") != []
        or not _evidence_ids(body.get("evidence_refs"))
        or not all(_support(item, scope) for item in supports)
    ):
        return False
    refs = list(body["evidence_refs"])
    if expiry is not None:
        if not isinstance(expiry, dict):
            return False
        expiry = cast(dict[str, Any], expiry)
        at = expiry.get("at")
        if (
            not {"at", "condition", "evidence_refs"} <= expiry.keys()
            or expiry["condition"] is not None
            or type(at) not in (int, float)
            or not math.isfinite(cast(float, at))
            or cast(float, at) < 0
            or not _evidence_ids(expiry["evidence_refs"])
        ):
            return False
        refs.extend(expiry["evidence_refs"])
    selected = cast(list[dict[str, Any]], supports)
    return (
        [item["id"] for item in selected] == list(dict.fromkeys(refs))
        and (row["cite"], row["quote"]) == (selected[0]["ref"], selected[0]["quote"])
        and type(row["revision"]) is int
        and row["revision"] > 0
        and isinstance(row["request_id"], str)
        and re.fullmatch(r"R_[0-9a-f]{32}", row["request_id"]) is not None
        and row["privacy_classification"] == "unknown"
        and _strings(row["privacy_checks"])
        and set(row["privacy_checks"]) >= PRIVACY_CHECKS
        and row["use_allowed"] is True
        and row["use_reason"] == "ok"
    )


def valid_row(value: object) -> bool:
    """Admit explicit uncited diagnostics or complete eligible Notes, retaining nested data."""
    if not isinstance(value, dict):
        return False
    row = cast(dict[str, Any], value)
    if set(row) not in (BASE_FIELDS, BASE_FIELDS | NOTE_FIELDS) or not all(
        isinstance(row.get(key), str) and bool(row[key].strip()) for key in ("id", "text", "scope")
    ):
        return False
    if set(row) == BASE_FIELDS:
        return row["cited"] is False and row["cite"] == "" and row["quote"] == "" and row["muninn_id"] is None
    return (
        row["cited"] is True
        and all(isinstance(row[key], str) and bool(row[key].strip()) for key in ("cite", "quote", "muninn_id"))
        and re.fullmatch(r"K_[0-9a-f]{32}", row["muninn_id"]) is not None
        and _metadata(row)
    )


def validate_snapshot(rows: list[object], digest: object) -> None:
    """Bind each complete row in query order; authored string lessons are outside this snapshot."""
    if not all(valid_row(row) for row in rows):
        raise ValueError("lessons reader returned an invalid lesson row")
    if digest != hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest():
        raise ValueError("lessons reader returned a wrong digest")


def query(progress: Path, push_script: Path, session: str) -> dict[str, Any]:
    """Run the provider's lesson reader against this graph's repo-key directory."""
    lock = Path(f"{progress}.lock")
    if lock.is_dir():
        raise ValueError("lessons query cannot run under the graph lock")
    if lock.is_file():
        with lock.open("r+", encoding="utf-8") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ValueError("lessons query cannot run under the graph lock") from error
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)
    reader = push_script.parent / "lib/lessons.py"
    done = subprocess.run(
        [
            sys.executable,
            str(reader),
            "--dir",
            str(progress.parent.parent),
            "--session",
            session,
            "query",
            "--format",
            "contract",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    try:
        payload: object = json.loads(done.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError("lessons reader returned invalid JSON") from error
    if done.returncode != 0:
        refusal = cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
        raw = refusal.get("reason_code") or refusal.get("degraded")
        reason = raw if isinstance(raw, str) and raw else "unavailable"
        raise ValueError(f"lessons reader refused: {reason}")
    if not isinstance(payload, dict):
        raise ValueError("lessons reader returned a non-object")
    found = cast(dict[str, Any], payload)
    rows, digest = found.get("lessons"), found.get("sha256")
    if not isinstance(rows, list) or not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("lessons reader returned an invalid contract")
    validate_snapshot(cast(list[object], rows), digest)
    return {"lessons": rows, "sha256": digest}


def needed(state: dict[str, Any], authorization: bool = False) -> bool:
    """Select a current snapshot for assigned inputs or issued lesson-bearing contracts."""
    if authorization:
        return needed(state) or any(
            row.get("contract", {}).get("lessons_sha256") is not None
            for row in state["graph"].get("dispatches", {}).values()
        )
    return any(
        unit.get(key) for unit in state.get("work_units", {}).values() for key in ("manifest", "worktree", "lessons")
    )
