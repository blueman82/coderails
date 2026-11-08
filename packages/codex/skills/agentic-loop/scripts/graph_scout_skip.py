"""Bind and recheck a scout stage that has no work to dispatch."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, cast

import graph_contract
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
    task_node,
)
from graph_scout_prior import prove_prior_refusal
from graph_transcript import thread_transcript

PREFIXES = {"S2.5": "no_design_fork:", "S2.6": "no_retired_path:"}
KEYS = {"kind", "attempt", "wave_id", "reason", "evidence_sha256", "cursor", "end_cursor", "transcript_sha256"}
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


def _approval(state: dict[str, Any], node_id: str, attempt: int, wave_id: str, cursor: int) -> dict[str, Any]:
    """Bind an exact assistant request to the next direct native user reply."""
    records = read_records(thread_transcript(state["session_id"]), "parent transcript")
    result_line = prove_prior_refusal(state, node_id, attempt, wave_id, cursor, records)
    request = _request(state, attempt)
    matches = [
        (line, text) for line, row in records if line > result_line if (text := _text(row, "assistant")) == request
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
        or type(reference.get("end_cursor")) is not int
        or reference["end_cursor"] < reference["cursor"]
        or not isinstance(reference.get("transcript_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", reference["transcript_sha256"])
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


def scout_absence(
    records: list[tuple[int, dict[str, Any]]], loop_id: str, node_id: str, cursor: int, end_cursor: int
) -> list[tuple[int, str]]:
    """Bind observed task identities through the saved boundary and reject any matching scout."""
    observed_tasks: list[tuple[int, str]] = []
    for line, record in records:
        if line <= cursor:
            continue
        payload = event_payload(record)
        raw_item = payload.get("item") if record.get("type") == "event_msg" else None
        item = cast(dict[str, Any], raw_item) if isinstance(raw_item, dict) else {}
        observed: object
        if (
            record.get("type") == "response_item"
            and payload.get("type") == "function_call"
            and payload.get("name") == "spawn_agent"
        ):
            try:
                arguments = object_value(json.loads(payload.get("arguments", "")), "native spawn arguments")
            except (TypeError, ValueError) as error:
                if line > end_cursor:
                    continue
                raise GraphError("scout skip cannot establish absence from an unreadable native request") from error
            observed = arguments.get("task_name")
        elif item.get("type") == "SubAgentActivity" and item.get("kind") == "started":
            path = item.get("agent_path")
            observed = path.removeprefix("/root/") if isinstance(path, str) else None
        elif item.get("type") == "CollabAgentToolCall" and item.get("tool") == "spawn_agent":
            prompt = item.get("prompt")
            observed = (
                prompt.split("\n", 1)[0].removeprefix("CODERAILS_GRAPH_TASK=") if isinstance(prompt, str) else None
            )
        else:
            continue
        if not isinstance(observed, str):
            if line > end_cursor:
                continue
            raise GraphError("scout skip cannot establish absence from an unidentified native request")
        try:
            owner = task_node(observed)
        except GraphError as error:
            if line > end_cursor:
                continue
            raise GraphError("scout skip cannot establish absence from an unidentified native task") from error
        if owner == (loop_id, node_id):
            raise GraphError(f"node {node_id} scout skip cannot reuse a native spawn")
        if line <= end_cursor:
            observed_tasks.append((line, observed))
    return observed_tasks


def no_spawn(
    state: dict[str, Any],
    node_id: str,
    expected: str,
    cursor: int,
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    refusals: dict[str, tuple[int, str]],
    end_cursor: int | None = None,
) -> dict[str, Any]:
    """Reject a skip if the current wave tried to start the scout."""
    records = read_records(thread_transcript(state["session_id"]), "parent transcript")
    end = records[-1][0] if end_cursor is None else end_cursor
    if end < cursor or end > records[-1][0]:
        raise GraphError("scout skip transcript interval is unavailable")
    interval = scout_absence(records, state["loop_id"], node_id, cursor, end)
    if any(line > cursor and task == expected for rows in indexes.values() for line, task, *_ in rows) or any(
        line > cursor and task == expected for line, task in refusals.values()
    ):
        raise GraphError(f"node {node_id} scout skip cannot reuse a native spawn")
    return {
        "end_cursor": end,
        "transcript_sha256": hashlib.sha256(
            json.dumps(interval, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def check_wave(state: dict[str, Any], node_id: str, attempt: int, wave_id: str, cursor: int) -> dict[str, Any]:
    """Require one unused issued scout slot with matching independent wave history."""
    graph = state["graph"]
    dispatches = object_value(graph.get("dispatches"), "scout skip dispatches")
    records = ((identifier, object_value(record, "scout dispatch")) for identifier, record in dispatches.items())
    issued = [
        (identifier, record)
        for identifier, record in records
        if record.get("node_id") == node_id and record.get("wave_id") == wave_id
    ]
    if len(issued) != 1:
        raise GraphError(f"node {node_id} scout skip needs exactly one issued dispatch")
    identifier, record = issued[0]
    if (
        record.get("attempt") != attempt
        or type(record.get("attempt")) is not int
        or record.get("authorized") is not None
        or "authorized" not in record
        or identifier != graph_contract.dispatch_id(state["loop_id"], wave_id, node_id, attempt)
    ):
        raise GraphError(f"node {node_id} has no unconsumed native skip wave")
    history = object_value(graph.get("wave_history"), "native wave history")
    wave = object_value(history.get(wave_id), "native wave history entry")
    if (
        wave.get("cursor") != cursor
        or type(wave.get("cursor")) is not int
        or not isinstance(wave.get("nodes"), list)
        or node_id not in wave.get("nodes", [])
        or type(wave.get("revision")) is not int
        or type(record.get("revision")) is not int
        or wave["revision"] != record.get("revision")
    ):
        raise GraphError(f"node {node_id} scout skip has a changed wave cursor or revision")
    return wave


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
        approval = _approval(state, node_id, attempt, active_wave["wave_id"], cursor)
    else:
        if attempt != 1:
            raise GraphError(f"node {node_id} no-work skip must precede any scout attempt")
        approval = {}
    interval = no_spawn(state, node_id, task_name(state["loop_id"], node_id, attempt), cursor, indexes, refusals)
    wave = check_wave(state, node_id, attempt, active_wave["wave_id"], cursor)
    if (
        active_wave.get("revision") != state["revision"]
        or wave["revision"] != active_wave["revision"]
        or wave["nodes"] != active_wave["nodes"]
    ):
        raise GraphError(f"node {node_id} scout skip does not own the active wave")
    return {
        "kind": "graph_skip",
        "attempt": attempt,
        "wave_id": active_wave["wave_id"],
        "reason": prefix[:-1],
        "evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
        "cursor": cursor,
        **interval,
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
    check_wave(state, node_id, attempt, reference["wave_id"], reference["cursor"])
    interval = no_spawn(
        state,
        node_id,
        task_name(state["loop_id"], node_id, attempt),
        reference["cursor"],
        indexes,
        refusals,
        reference["end_cursor"],
    )
    if interval["transcript_sha256"] != reference["transcript_sha256"]:
        raise GraphError("scout skip transcript interval changed")
    if approved:
        if not any(
            isinstance(item, dict) and cast(dict[str, Any], item).get("outcome") == REFUSED_OUTCOME
            for item in cast(list[object], node["evidence"])
        ):
            raise GraphError("non-independent skip has no prior refused scout attempt")
        approval = _approval(state, node_id, attempt, reference["wave_id"], reference["cursor"])
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
