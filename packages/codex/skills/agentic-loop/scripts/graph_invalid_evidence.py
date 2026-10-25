"""Bind a completed native spawn with no plaintext dispatch envelope."""

from __future__ import annotations

from typing import Any

from graph_data import read_records
from graph_evidence import stored_references, verify_reference
from graph_identity import INVALID_DISPATCH_OUTCOME, GraphError, next_attempt, task_name
from graph_transcript import (
    child_terminal,
    native_dispatch_requests,
    parent_indexes,
    refused_launches,
    thread_transcript,
)


def bind_invalid_dispatch(state: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Bind one completed native spawn whose issued dispatch lacks a plaintext envelope."""
    active = state["graph"]["active_wave"]
    if active is None or active["nodes"] != [node_id]:
        raise GraphError("invalid dispatch recovery requires a single-node active wave")
    parent = read_records(thread_transcript(state["session_id"]), "parent transcript")
    indexes, refusals = parent_indexes(parent), refused_launches(parent)
    requests = native_dispatch_requests(parent)
    attempt = next_attempt(state["graph"]["nodes"][node_id])
    expected = task_name(state["loop_id"], node_id, attempt)
    matches = [
        (call, rows[0])
        for call, rows in indexes.items()
        if len(rows) == 1 and rows[0][0] > active["transcript_cursor"] and rows[0][1] == expected
    ]
    if len(matches) != 1 or any(
        line > active["transcript_cursor"] and task == expected for line, task in refusals.values()
    ):
        raise GraphError("invalid dispatch recovery requires one unique native spawn")
    call, (_, _, child, nickname, path, role) = matches[0]
    terminal = child_terminal(state["session_id"], child, nickname, path, role)
    reference = {
        "kind": "codex_agent",
        "attempt": attempt,
        "wave_id": active["wave_id"],
        "spawn_call_id": call,
        "agent_thread_id": child,
        "task_complete_turn_id": terminal,
        "outcome": INVALID_DISPATCH_OUTCOME,
    }
    verify_reference(state, node_id, reference, indexes, refusals, requests)
    stored_references(state, False, {call, child, terminal})
    return reference
