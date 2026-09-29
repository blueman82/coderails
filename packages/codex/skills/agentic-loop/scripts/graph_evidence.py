"""Bind and revalidate native worker evidence against graph attempts."""

from __future__ import annotations

import re
from typing import Any, cast

from graph_artifacts import validate_completion_evidence as validate_completion_evidence
from graph_artifacts import validate_evals as validate_evals
from graph_data import nonempty, object_value, read_records
from graph_identity import (
    REFERENCE_KEYS,
    GraphError,
    classify_worker_evidence,
    legacy_task_name,
    next_attempt,
    task_name,
)
from graph_transcript import child_read_records, child_terminal, parent_indexes, thread_transcript
from graph_transcript import transcript_cursor as transcript_cursor


def _reference(value: object, label: str) -> dict[str, Any]:
    reference = object_value(value, label)
    if set(reference) != REFERENCE_KEYS or reference.get("kind") != "codex_agent":
        raise GraphError(f"{label} has invalid transcript reference fields")
    attempt = reference.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise GraphError(f"{label}.attempt must be a positive integer")
    for key in REFERENCE_KEYS - {"kind", "attempt"}:
        nonempty(reference.get(key), f"{label}.{key}")
    return reference


def _verify_reference(
    state: dict[str, Any],
    node_id: str,
    reference: dict[str, Any],
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    allow_legacy: bool = False,
) -> int:
    spawns = indexes
    expected_task = task_name(state["loop_id"], node_id, reference["attempt"])
    call_id = reference["spawn_call_id"]
    if len(spawns.get(call_id, [])) != 1:
        raise GraphError(f"node {node_id} spawn reference is missing or duplicate")
    spawn_line, observed_task, observed_agent, nickname, expected_path, expected_role = spawns[call_id][0]
    legacy_match = allow_legacy and observed_task == legacy_task_name(node_id, reference["attempt"])
    if (observed_task != expected_task and not legacy_match) or observed_agent != reference["agent_thread_id"]:
        raise GraphError(f"node {node_id} spawn reference has the wrong task")
    terminal = child_terminal(state["session_id"], reference["agent_thread_id"], nickname, expected_path, expected_role)
    if terminal != reference["task_complete_turn_id"]:
        raise GraphError(f"node {node_id} task_complete reference does not match its child")
    return spawn_line


def _validate_missing_attempts(
    state: dict[str, Any],
    node_id: str,
    maximum: int,
    references: list[tuple[dict[str, Any], set[str]]],
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    used: set[str],
) -> None:
    completed = {reference["attempt"]: reference for reference, _ in references}
    previous_line = 0
    for attempt in range(1, maximum + 1):
        if attempt in completed:
            line = _verify_reference(state, node_id, completed[attempt], indexes, allow_legacy=True)
        else:
            expected = task_name(state["loop_id"], node_id, attempt)
            matches = [
                (call, items[0]) for call, items in indexes.items() if len(items) == 1 and items[0][1] == expected
            ]
            if len(matches) != 1:
                raise GraphError(f"node {node_id} stale attempt has no unique native spawn")
            call, (line, _, child, nickname, path, role) = matches[0]
            if used & {call, child}:
                raise GraphError(f"node {node_id} stale attempt reuses native identity")
            child_read_records(state["session_id"], child, nickname, path, role)
            used.update({call, child})
        if line <= previous_line:
            raise GraphError(f"node {node_id} native attempts are stale or out of order")
        previous_line = line


def _stored_references(
    state: dict[str, Any], require_complete: bool, known_identifiers: set[str] | None = None
) -> set[str]:
    indexes = parent_indexes(read_records(thread_transcript(state["session_id"]), "parent transcript"))
    used = set(known_identifiers or ())
    waves: set[int] = set()
    ordinary: list[object] = []
    for node_id, node in state["graph"]["nodes"].items():
        if node_id in state["graph"]["joins"]:
            ordinary.extend(node["evidence"])
            continue
        references: list[tuple[dict[str, Any], set[str]]] = []
        for index, item in enumerate(node["evidence"]):
            shaped, identifiers = classify_worker_evidence(item)
            if not shaped:
                ordinary.append(item)
                continue
            references.append((_reference(item, f"node {node_id}.evidence[{index}]"), identifiers))
        expected_count = node["retry"]["attempts"] + (1 if node["status"] in {"done", "skipped"} else 0)
        attempts = sorted(item[0]["attempt"] for item in references)
        maximum = next_attempt(node) if node["status"] in {"done", "skipped", "stale"} else next_attempt(node) - 1
        if (
            len(attempts) != expected_count
            or len(set(attempts)) != len(attempts)
            or any(attempt > maximum for attempt in attempts)
            or (node["status"] in {"done", "skipped"} and (not attempts or attempts[-1] != maximum))
        ):
            raise GraphError(f"node {node_id} transcript attempts do not match its graph state")
        if require_complete and node["status"] not in {"done", "skipped"}:
            raise GraphError(f"node {node_id} has no completed transcript-backed attempt")
        previous_line = previous_wave = 0
        for reference, identifiers in sorted(references, key=lambda item: item[0]["attempt"]):
            match = re.fullmatch(r"wave-([1-9][0-9]*)", reference["wave_id"])
            wave = int(match.group(1)) if match else 0
            if wave <= previous_wave:
                raise GraphError(f"node {node_id} has stale or invalid wave evidence")
            previous_wave = wave
            waves.add(wave)
            if used & identifiers:
                raise GraphError(f"node {node_id} reuses transcript evidence")
            used.update(identifiers)
            spawn_line = _verify_reference(state, node_id, reference, indexes, allow_legacy=True)
            if spawn_line <= previous_line:
                raise GraphError(f"node {node_id} transcript attempts are stale or out of order")
            previous_line = spawn_line
        _validate_missing_attempts(state, node_id, maximum, references, indexes, used)
    if waves:
        completion = state.get("completion") if state.get("status") == "complete" else None
        completion = cast(dict[str, Any], completion) if isinstance(completion, dict) else None
        revision = completion.get("revision") if completion is not None else state["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int):
            raise GraphError("graph revision must be an integer")
        last_wave = revision - (2 if state["graph"]["active_wave"] is not None else 1)
        generations = sum(node["respawn"]["generation"] for node in state["graph"]["nodes"].values())
        ordered = sorted(waves)
        # Respawn transitions advance revisions without dispatching a wave.
        gaps = sum(right - left - 2 for left, right in zip(ordered, ordered[1:]))
        if max(waves) > last_wave or any(right - left < 2 for left, right in zip(ordered, ordered[1:])):
            raise GraphError("stored worker wave evidence does not match graph revisions")
        if gaps < 0 or gaps + last_wave - max(waves) > 3 * generations + (
            2 if any(node["status"] == "stale" for node in state["graph"]["nodes"].values()) else 0
        ):
            raise GraphError("stored worker wave evidence does not match graph revisions")
    if any(classify_worker_evidence(item, used)[0] for item in ordinary):
        raise GraphError("stored evidence contains noncanonical worker evidence")
    return used


def bind_worker_evidence(
    state: dict[str, Any], active_wave: dict[str, Any], stale_nodes: frozenset[str] = frozenset()
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Bind current-wave transcript records to each dispatched worker node."""
    used: set[str] = set()
    parent = read_records(thread_transcript(state["session_id"]), "parent transcript")
    indexes = parent_indexes(parent)
    cursor = active_wave.get("transcript_cursor")
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 1:
        raise GraphError("active wave has no valid transcript cursor")
    references: dict[str, dict[str, Any]] = {}
    for node_id in active_wave["nodes"]:
        attempt = next_attempt(state["graph"]["nodes"][node_id])
        expected_task = task_name(state["loop_id"], node_id, attempt)
        matching = [
            (call_id, items[0])
            for call_id, items in indexes.items()
            if len(items) == 1 and items[0][0] > cursor and items[0][1] == expected_task
        ]
        if len(matching) != 1:
            raise GraphError(f"node {node_id} must have exactly one current-wave spawn")
        call_id, (_, _, agent_thread_id, nickname, expected_path, expected_role) = matching[0]
        if node_id in stale_nodes:
            child_read_records(state["session_id"], agent_thread_id, nickname, expected_path, expected_role)
            continue
        terminal = child_terminal(state["session_id"], agent_thread_id, nickname, expected_path, expected_role)
        reference = {
            "kind": "codex_agent",
            "attempt": attempt,
            "wave_id": active_wave["wave_id"],
            "spawn_call_id": call_id,
            "agent_thread_id": agent_thread_id,
            "task_complete_turn_id": terminal,
        }
        identifiers = {call_id, agent_thread_id, terminal}
        if used & identifiers:
            raise GraphError(f"node {node_id} reuses transcript evidence")
        _verify_reference(state, node_id, reference, indexes)
        used.update(identifiers)
        references[node_id] = reference
    used = _stored_references(state, False, used)
    return references, used


def validate_worker_evidence(state: dict[str, Any]) -> None:
    """Validate all stored worker evidence against native transcripts."""
    _stored_references(state, True)
