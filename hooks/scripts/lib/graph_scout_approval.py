"""Bind a failed design-scout fallback to a direct owner reply."""

from __future__ import annotations

import hashlib
from typing import Any, cast

from .graph_evidence import parent_records, transcript


def _text(record: dict[str, Any], role: str) -> str | None:
    if record.get("type") != role:
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    message = cast(dict[str, Any], message)
    if message.get("role") != role:
        return None
    value = message.get("content")
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return None
    blocks = cast(list[object], value)
    if len(blocks) == 1 and isinstance(blocks[0], dict):
        block = cast(dict[str, Any], blocks[0])
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            return cast(str, block["text"])
    return None


def approval(state: dict[str, Any], node_id: str, attempt: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Find one assistant request followed by the next direct user reply."""
    node = state["graph"]["nodes"][node_id]
    prior: list[dict[str, Any]] = []
    for value in cast(list[object], node["evidence"]):
        if isinstance(value, dict):
            ref = cast(dict[str, Any], value)
            if (
                ref.get("kind") == "claude_agent"
                and ref.get("outcome") == "failed"
                and ref.get("attempt") == attempt - 1
            ):
                prior.append(ref)
    if node_id != "S2.5" or len(prior) != 1:
        raise ValueError("non-independent skip needs a recorded scout spawn refusal")
    failed = [
        row
        for row in rows
        if row["tool_use_id"] == prior[0].get("tool_use_id")
        and row["node_id"] == node_id
        and row["native_result"].get("is_error") is True
    ]
    if len(failed) != 1:
        raise ValueError("non-independent skip has no native refused scout call")
    request = (
        "Coderails: Approve a non-independent design-scout fallback for loop "
        f"{state['loop_id']}, node S2.5, attempt {attempt}? Reply approve or deny."
    )
    records = parent_records(transcript(state["session_id"]), state["session_id"])
    requests = [
        (line, text)
        for line, row in records
        if line > failed[0]["line"]
        if (text := _text(row, "assistant")) == request
    ]
    if len(requests) != 1:
        raise ValueError("non-independent skip has no unique native approval request")
    request_line, _ = requests[0]
    replies = [
        (line, row)
        for line, row in records
        if line > request_line
        if row.get("type") in {"assistant", "user"}
        and isinstance(row.get("message"), dict)
        and row["message"].get("role") == row["type"]
    ]
    if (
        not replies
        or (approval_text := _text(replies[0][1], "user")) is None
        or approval_text.strip().casefold() != "approve"
    ):
        raise ValueError("non-independent skip has no explicit native user approval")
    assert approval_text is not None
    approval_line = replies[0][0]
    return {
        "request_line": request_line,
        "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
        "approval_line": approval_line,
        "approval_sha256": hashlib.sha256(approval_text.encode()).hexdigest(),
    }
