"""Bind and recheck a scout stage that has no work to dispatch."""

from __future__ import annotations

import hashlib
import re
from typing import Any, cast

from graph_data import event_payload, nonempty, object_value, read_records
from graph_identity import (
    ENCRYPTED_REFERENCE_KEYS,
    INVALID_DISPATCH_KEYS,
    INVALID_DISPATCH_OUTCOME,
    REFERENCE_KEYS,
    REFUSED_KEYS,
    REFUSED_OUTCOME,
    GraphError,
    task_name,
)
from graph_transcript import thread_transcript

PREFIXES = {"S2.5": "no_design_fork:", "S2.6": "no_retired_path:"}
KEYS = {"kind", "attempt", "wave_id", "reason", "evidence_sha256", "cursor"}
APPROVAL_KEYS = KEYS | {"request_line", "request_sha256", "approval_line", "approval_sha256"}


def _request(state: dict[str, Any], attempt: int) -> str:
    return (
        "Coderails: Approve a non-independent design-scout fallback for loop "
        f"{state['loop_id']}, node S2.5, attempt {attempt}? Reply approve or deny."
    )


def _text(record: dict[str, Any], role: str) -> str | None:
    payload = event_payload(record)
    content = payload.get("content")
    kind = "output_text" if role == "assistant" else "input_text"
    if (
        record.get("type") != "response_item"
        or payload.get("type") != "message"
        or payload.get("role") != role
        or not isinstance(content, list)
    ):
        return None
    blocks = cast(list[object], content)
    if len(blocks) != 1 or not isinstance(blocks[0], dict):
        return None
    block = cast(dict[str, Any], blocks[0])
    if block.get("type") != kind or not isinstance(block.get("text"), str):
        return None
    return cast(str, block["text"])


def _approval(
    state: dict[str, Any], node_id: str, attempt: int, refusals: dict[str, tuple[int, str]]
) -> dict[str, Any]:
    """Bind an exact assistant request to the next direct native user reply."""
    node = state["graph"]["nodes"][node_id]
    prior: list[dict[str, Any]] = []
    for value in cast(list[object], node["evidence"]):
        if isinstance(value, dict):
            item = cast(dict[str, Any], value)
            if (
                item.get("kind") == "codex_agent"
                and item.get("outcome") == REFUSED_OUTCOME
                and item.get("attempt") == attempt - 1
            ):
                prior.append(item)
    if node_id != "S2.5" or len(prior) != 1:
        raise GraphError("non-independent skip needs a recorded scout spawn refusal")
    call_id = prior[0].get("spawn_call_id")
    refused = refusals.get(call_id) if isinstance(call_id, str) else None
    if refused is None or refused[1] != task_name(state["loop_id"], node_id, attempt - 1):
        raise GraphError("non-independent skip has no native refused scout call")
    records = read_records(thread_transcript(state["session_id"]), "parent transcript")
    request = _request(state, attempt)
    matches = [
        (line, text) for line, row in records if line > refused[0] if (text := _text(row, "assistant")) == request
    ]
    if len(matches) != 1:
        raise GraphError("non-independent skip has no unique native approval request")
    request_line, _ = matches[0]
    replies = [
        (line, row)
        for line, row in records
        if line > request_line
        if row.get("type") == "response_item"
        and event_payload(row).get("type") == "message"
        and event_payload(row).get("role") in {"assistant", "user"}
    ]
    if (
        not replies
        or (approval_text := _text(replies[0][1], "user")) is None
        or approval_text.strip().casefold() != "approve"
    ):
        raise GraphError("non-independent skip has no explicit native user approval")
    assert approval_text is not None
    approval_line = replies[0][0]
    return {
        "request_line": request_line,
        "request_sha256": hashlib.sha256(request.encode()).hexdigest(),
        "approval_line": approval_line,
        "approval_sha256": hashlib.sha256(approval_text.encode()).hexdigest(),
    }


def parse_reference(value: object, label: str) -> dict[str, Any]:
    """Validate the stored shape of a scout skip or native worker attempt."""
    reference = object_value(value, label)
    if reference.get("kind") == "graph_skip":
        check_shape(reference, label)
        return reference
    refused = set(reference) == REFUSED_KEYS and reference.get("outcome") == REFUSED_OUTCOME
    invalid = set(reference) == INVALID_DISPATCH_KEYS and reference.get("outcome") == INVALID_DISPATCH_OUTCOME
    encrypted = set(reference) == ENCRYPTED_REFERENCE_KEYS
    if (
        not (refused or invalid or encrypted or set(reference) == REFERENCE_KEYS)
        or reference.get("kind") != "codex_agent"
    ):
        raise GraphError(f"{label} has invalid transcript reference fields")
    attempt = reference.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise GraphError(f"{label}.attempt must be a positive integer")
    for key in set(reference) - {"kind", "attempt"}:
        nonempty(reference.get(key), f"{label}.{key}")
    if encrypted and not re.fullmatch(r"[0-9a-f]{64}", reference["message_sha256"]):
        raise GraphError(f"{label}.message_sha256 must be a SHA-256 digest")
    return reference


def check_shape(reference: dict[str, Any], label: str) -> None:
    """Require the compact skip reference fields."""
    if (
        set(reference) != (APPROVAL_KEYS if reference.get("reason") == "non_independent" else KEYS)
        or type(reference.get("attempt")) is not int
        or reference["attempt"] < (2 if reference.get("reason") == "non_independent" else 1)
        or (reference.get("reason") != "non_independent" and reference["attempt"] != 1)
        or type(reference.get("cursor")) is not int
        or reference["cursor"] < 1
        or not isinstance(reference.get("wave_id"), str)
        or not re.fullmatch(r"wave-[1-9][0-9]*", reference["wave_id"])
        or not isinstance(reference.get("evidence_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", reference["evidence_sha256"])
        or (
            reference.get("reason") == "non_independent"
            and (
                type(reference.get("request_line")) is not int
                or type(reference.get("approval_line")) is not int
                or reference["request_line"] < 1
                or reference["approval_line"] <= reference["request_line"]
                or any(
                    not isinstance(reference.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", reference[key])
                    for key in ("request_sha256", "approval_sha256")
                )
            )
        )
    ):
        raise GraphError(f"{label} has invalid scout skip fields")


def no_spawn(
    node_id: str,
    expected: str,
    cursor: int,
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    refusals: dict[str, tuple[int, str]],
) -> None:
    """Reject a skip if the current wave tried to start the scout."""
    if any(line > cursor and task == expected for rows in indexes.values() for line, task, *_ in rows) or any(
        line > cursor and task == expected for line, task in refusals.values()
    ):
        raise GraphError(f"node {node_id} scout skip cannot reuse a native spawn")


def bind(
    state: dict[str, Any],
    active_wave: dict[str, Any],
    node_id: str,
    evidence: str,
    cursor: int,
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    refusals: dict[str, tuple[int, str]],
) -> dict[str, Any]:
    """Create a scoped no-work or approved-fallback skip reference."""
    node = state["graph"]["nodes"][node_id]
    approved = evidence.startswith("non_independent:")
    prefix = "non_independent:" if approved else PREFIXES.get(node_id)
    attempt = node["retry"]["attempts"] + 1
    if (
        prefix is None
        or not evidence.startswith(prefix)
        or not evidence[len(prefix) :].strip()
        or node["respawn"]["generation"]
    ):
        raise GraphError(f"node {node_id} has invalid scout skip reason")
    if approved:
        if (
            node_id != "S2.5"
            or node["retry"]["attempts"] < 1
            or not evidence.startswith("non_independent: human approved")
        ):
            raise GraphError("non-independent skip needs a prior refusal and explicit approval")
        approval = _approval(state, node_id, attempt, refusals)
    else:
        if attempt != 1:
            raise GraphError(f"node {node_id} no-work skip must precede any scout attempt")
        approval = {}
    no_spawn(node_id, task_name(state["loop_id"], node_id, attempt), cursor, indexes, refusals)
    return {
        "kind": "graph_skip",
        "attempt": attempt,
        "wave_id": active_wave["wave_id"],
        "reason": prefix[:-1],
        "evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
        "cursor": cursor,
        **approval,
    }


def verify(
    state: dict[str, Any],
    node_id: str,
    reference: dict[str, Any],
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    refusals: dict[str, tuple[int, str]],
) -> int:
    """Check the saved skip against its reason and unconsumed wave."""
    node = state["graph"]["nodes"][node_id]
    approved = reference["reason"] == "non_independent"
    prefix = "non_independent:" if approved else PREFIXES.get(node_id)
    attempt = node["retry"]["attempts"] + 1
    if (
        prefix is None
        or node["status"] != "skipped"
        or node["respawn"]["generation"] != 0
        or reference["attempt"] != attempt
        or (not approved and attempt != 1)
        or reference["reason"] != prefix[:-1]
    ):
        raise GraphError(f"node {node_id} has invalid scout skip evidence")
    dispatches = cast(dict[str, dict[str, Any]], state["graph"].get("dispatches", {}))
    issued = [
        record
        for record in dispatches.values()
        if record.get("node_id") == node_id
        and record.get("wave_id") == reference["wave_id"]
        and record.get("attempt") == attempt
    ]
    if len(issued) != 1 or issued[0].get("authorized") is not None:
        raise GraphError(f"node {node_id} has no unconsumed native skip wave")
    history = cast(dict[str, dict[str, Any]], state["graph"].get("wave_history", {}))
    wave = history.get(reference["wave_id"])
    if (
        not isinstance(wave, dict)
        or wave.get("cursor") != reference["cursor"]
        or type(wave.get("cursor")) is not int
        or node_id not in wave.get("nodes", [])
        or wave.get("revision") != issued[0].get("revision")
    ):
        raise GraphError(f"node {node_id} scout skip has a changed wave cursor")
    no_spawn(node_id, task_name(state["loop_id"], node_id, attempt), reference["cursor"], indexes, refusals)
    if approved:
        if not any(
            isinstance(item, dict) and cast(dict[str, Any], item).get("outcome") == REFUSED_OUTCOME
            for item in cast(list[object], node["evidence"])
        ):
            raise GraphError("non-independent skip has no prior refused scout attempt")
        approval = _approval(state, node_id, attempt, refusals)
        if any(reference.get(key) != value for key, value in approval.items()):
            raise GraphError("non-independent skip approval reference changed")
    matching = [
        item
        for item in node["evidence"]
        if isinstance(item, str)
        and item.startswith(prefix)
        and item[len(prefix) :].strip()
        and hashlib.sha256(item.encode()).hexdigest() == reference["evidence_sha256"]
    ]
    if len(matching) != 1:
        raise GraphError(f"node {node_id} scout skip reason changed")
    return cast(int, reference["cursor"])
