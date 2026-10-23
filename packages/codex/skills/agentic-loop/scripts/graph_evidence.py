"""Bind and revalidate native worker evidence against graph attempts."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional, cast

import graph_contract
import graph_encrypted_content
from graph_artifacts import validate_completion_evidence as validate_completion_evidence
from graph_artifacts import validate_evals as validate_evals
from graph_data import nonempty, object_value, read_records
from graph_identity import (
    ENCRYPTED_REFERENCE_KEYS,
    INVALID_DISPATCH_KEYS,
    INVALID_DISPATCH_OUTCOME,
    REFERENCE_KEYS,
    REFUSED_KEYS,
    REFUSED_OUTCOME,
    GraphError,
    classify_worker_evidence,
    is_legacy_task_name,
    new_evidence_writes_enabled,
    next_attempt,
    task_name,
)
from graph_recovery import RecoveryRefusedError
from graph_transcript import (
    child_read_records,
    child_terminal,
    native_dispatch_requests,
    parent_indexes,
    refused_launches,
    thread_transcript,
)

Refusals = dict[str, tuple[int, str]]
Requests = dict[str, list[Optional[dict[str, Any]]]]
LEGACY_REFUSED = "legacy_task_identity_refused"


def _legacy_refusal(node_id: str, attempt: object) -> RecoveryRefusedError:
    """Return the stable refusal for a node-only (pre-loop-scoped) task name; it is never bound or skipped."""
    message = (
        f"node {node_id} attempt {attempt} carries a pre-loop-scoped task name; re-dispatch under the loop-scoped name"
    )
    return RecoveryRefusedError(LEGACY_REFUSED, message, (node_id,), attempt if isinstance(attempt, int) else None)


def _reference(value: object, label: str) -> dict[str, Any]:
    reference = object_value(value, label)
    refused = set(reference) == REFUSED_KEYS and reference.get("outcome") == REFUSED_OUTCOME
    invalid = set(reference) == INVALID_DISPATCH_KEYS and reference.get("outcome") == INVALID_DISPATCH_OUTCOME
    encrypted = set(reference) == ENCRYPTED_REFERENCE_KEYS
    valid = refused or invalid or encrypted or set(reference) == REFERENCE_KEYS
    if not valid or reference.get("kind") != "codex_agent":
        raise GraphError(f"{label} has invalid transcript reference fields")
    attempt = reference.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise GraphError(f"{label}.attempt must be a positive integer")
    for key in set(reference) - {"kind", "attempt"}:
        nonempty(reference.get(key), f"{label}.{key}")
    if encrypted and not re.fullmatch(r"[0-9a-f]{64}", reference["message_sha256"]):
        raise GraphError(f"{label}.message_sha256 must be a SHA-256 digest")
    return reference


def _verify_dispatch(
    state: dict[str, Any], node_id: str, attempt: int, wave_id: str, call_id: str, requests: Requests
) -> None:
    """Recheck the native message and consumed v2 record for a contract-era Codex spawn."""
    start = state["graph"].get("contract_from_revision")
    wave = re.fullmatch(r"wave-([1-9][0-9]*)", wave_id)
    if type(start) is not int or not wave or int(wave.group(1)) < start:
        return
    calls = requests.get(call_id, [])
    if len(calls) != 1 or not isinstance(calls[0], dict):
        raise graph_contract.DispatchDeniedError("dispatch_missing_envelope", "native spawn has no unique request")
    request = calls[0]
    message = request.get("message")
    if not isinstance(message, str):
        raise graph_contract.DispatchDeniedError("dispatch_missing_envelope", "native spawn has no message")
    if request.get("task_name") != task_name(state["loop_id"], node_id, attempt):
        raise graph_contract.DispatchDeniedError("dispatch_foreign", "native spawn task name differs from its attempt")
    try:
        envelope = graph_contract.parse_envelope(message)
    except graph_contract.DispatchDeniedError as error:
        if error.code != "dispatch_missing_envelope":
            raise
        record = graph_encrypted_content.check(state, node_id, attempt, wave_id, message)
    else:
        record = graph_contract.check_ownership(state, envelope, live=False)
        if not (graph_contract.dispatch_off() or record.get("authorized") == {"tool_use_id": None, "mode": "off"}):
            record = graph_contract.check_dispatch(state, envelope, message, live=False)
    if (
        record.get("task_name") != request["task_name"]
        or record.get("attempt") != attempt
        or record["wave_id"] != wave_id
    ):
        raise graph_contract.DispatchDeniedError("dispatch_foreign", "native spawn does not own this graph attempt")
    if graph_contract.dispatch_off() or record.get("authorized") == {"tool_use_id": None, "mode": "off"}:
        return
    agent_type = request.get("agent_type", "")
    if not isinstance(agent_type, str):
        raise graph_contract.DispatchDeniedError("role_mismatch", "native spawn has an invalid agent type")
    graph_contract.assert_role(record["contract"], agent_type, "", None)
    if record.get("authorized") != {"tool_use_id": None}:
        raise graph_contract.DispatchDeniedError(
            "dispatch_unauthorized", "native spawn has no consumed dispatch authorization"
        )


def _verify_reference(
    state: dict[str, Any],
    node_id: str,
    reference: dict[str, Any],
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    refusals: Refusals,
    requests: Requests,
) -> int:
    spawns = indexes
    expected_task = task_name(state["loop_id"], node_id, reference["attempt"])
    call_id = reference["spawn_call_id"]
    if reference.get("outcome") == REFUSED_OUTCOME:
        if call_id in spawns or call_id not in refusals or refusals[call_id][1] != expected_task:
            raise GraphError(f"node {node_id} refused-launch reference does not match the parent transcript")
        return refusals[call_id][0]
    if any(is_legacy_task_name(item[1]) for item in spawns.get(call_id, [])):
        raise _legacy_refusal(node_id, reference["attempt"])
    if len(spawns.get(call_id, [])) != 1:
        raise GraphError(f"node {node_id} spawn reference is missing or duplicate")
    spawn_line, observed_task, observed_agent, nickname, expected_path, expected_role = spawns[call_id][0]
    if observed_task != expected_task or observed_agent != reference["agent_thread_id"]:
        raise GraphError(f"node {node_id} spawn reference has the wrong task")
    if reference.get("outcome") == INVALID_DISPATCH_OUTCOME:
        issued = [
            record
            for record in state["graph"].get("dispatches", {}).values()
            if record.get("node_id") == node_id
            and record.get("attempt") == reference["attempt"]
            and record.get("wave_id") == reference["wave_id"]
        ]
        if len(issued) != 1 or issued[0].get("authorized") is not None:
            raise GraphError(f"node {node_id} invalid dispatch has no unconsumed issued record")
        try:
            _verify_dispatch(state, node_id, reference["attempt"], reference["wave_id"], call_id, requests)
        except graph_contract.DispatchDeniedError as error:
            if error.code != "dispatch_missing_envelope":
                raise GraphError(f"node {node_id} invalid dispatch has a different refusal") from error
        else:
            raise GraphError(f"node {node_id} invalid dispatch now has a valid envelope")
    else:
        _verify_dispatch(state, node_id, reference["attempt"], reference["wave_id"], call_id, requests)
    if "message_sha256" in reference:
        message = cast(dict[str, Any], requests[call_id][0]).get("message")
        if not isinstance(message, str) or hashlib.sha256(message.encode()).hexdigest() != reference["message_sha256"]:
            raise GraphError(f"node {node_id} encrypted native message changed")
    child_terminal(
        state["session_id"],
        reference["agent_thread_id"],
        nickname,
        expected_path,
        expected_role,
        reference["task_complete_turn_id"],
    )
    return spawn_line


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
    _verify_reference(state, node_id, reference, indexes, refusals, requests)
    _stored_references(state, False, {call, child, terminal})
    return reference


def _validate_missing_attempts(
    state: dict[str, Any],
    node_id: str,
    maximum: int,
    references: list[tuple[dict[str, Any], set[str]]],
    indexes: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]],
    refusals: Refusals,
    requests: Requests,
    used: set[str],
) -> None:
    completed = {reference["attempt"]: reference for reference, _ in references}
    previous_line = 0
    for attempt in range(1, maximum + 1):
        if attempt in completed:
            line = _verify_reference(state, node_id, completed[attempt], indexes, refusals, requests)
        else:
            expected = task_name(state["loop_id"], node_id, attempt)
            matches = [
                (call, items[0]) for call, items in indexes.items() if len(items) == 1 and items[0][1] == expected
            ]
            if len(matches) != 1:
                legacy = f"loop_worker_{node_id.encode().hex()}" + ("" if attempt == 1 else f"_a{attempt}")
                if any(item[1] == legacy for items in indexes.values() for item in items):
                    raise _legacy_refusal(node_id, attempt)
                raise GraphError(f"node {node_id} stale attempt has no unique native spawn")
            call, (line, _, child, nickname, path, role) = matches[0]
            if used & {call, child}:
                raise GraphError(f"node {node_id} stale attempt reuses native identity")
            issued = [
                record
                for record in state["graph"].get("dispatches", {}).values()
                if record.get("node_id") == node_id and record.get("attempt") == attempt
            ]
            if len(issued) > 1:
                raise GraphError(f"node {node_id} stale attempt has ambiguous dispatch records")
            if not issued:
                raise graph_contract.DispatchDeniedError(
                    "dispatch_missing_envelope", "stale attempt has no stored wave revision"
                )
            _verify_dispatch(state, node_id, attempt, issued[0]["wave_id"], call, requests)
            child_read_records(state["session_id"], child, nickname, path, role)
            used.update({call, child})
        if line <= previous_line:
            raise GraphError(f"node {node_id} native attempts are stale or out of order")
        previous_line = line


def _stored_references(
    state: dict[str, Any], require_complete: bool, known_identifiers: set[str] | None = None
) -> set[str]:
    parent = read_records(thread_transcript(state["session_id"]), "parent transcript")
    indexes, refusals = parent_indexes(parent), refused_launches(parent)
    requests = native_dispatch_requests(parent)
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
        if node["status"] in {"done", "skipped"} and any(
            item[0].get("outcome") == REFUSED_OUTCOME and item[0]["attempt"] == maximum for item in references
        ):
            raise GraphError(f"node {node_id} completed attempt cannot rest on a refused launch")
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
            spawn_line = _verify_reference(state, node_id, reference, indexes, refusals, requests)
            if spawn_line <= previous_line:
                raise GraphError(f"node {node_id} transcript attempts are stale or out of order")
            previous_line = spawn_line
        _validate_missing_attempts(state, node_id, maximum, references, indexes, refusals, requests, used)
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
    state: dict[str, Any],
    active_wave: dict[str, Any],
    stale_nodes: frozenset[str] = frozenset(),
    failed_nodes: frozenset[str] = frozenset(),
) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Bind wave records; a failed node may use its last refused spawn_agent call."""
    used: set[str] = set()
    parent = read_records(thread_transcript(state["session_id"]), "parent transcript")
    indexes, refusals = parent_indexes(parent), refused_launches(parent)
    requests = native_dispatch_requests(parent)
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
        refused = [(line, call) for call, (line, task) in refusals.items() if line > cursor and task == expected_task]
        if not matching and node_id in failed_nodes and refused:
            call_id = max(refused)[1]
            reference = {
                "kind": "codex_agent",
                "attempt": attempt,
                "wave_id": active_wave["wave_id"],
                "spawn_call_id": call_id,
                "outcome": REFUSED_OUTCOME,
            }
            if call_id in used:
                raise GraphError(f"node {node_id} reuses transcript evidence")
            _verify_reference(state, node_id, reference, indexes, refusals, requests)
            used.add(call_id)
            references[node_id] = reference
            continue
        if len(matching) != 1:
            raise GraphError(f"node {node_id} must have exactly one current-wave spawn")
        call_id, (_, _, agent_thread_id, nickname, expected_path, expected_role) = matching[0]
        _verify_dispatch(state, node_id, attempt, active_wave["wave_id"], call_id, requests)
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
        request = next(iter(requests.get(call_id, ())), None)
        message = request.get("message") if isinstance(request, dict) else None
        if isinstance(message, str) and not message.startswith(graph_contract.ENVELOPE_KEY + "="):
            if not new_evidence_writes_enabled():
                raise GraphError("set CODERAILS_A6_EVIDENCE_WRITE=on after reader verification")
            reference["message_sha256"] = hashlib.sha256(message.encode()).hexdigest()
        identifiers = {call_id, agent_thread_id, terminal}
        if used & identifiers:
            raise GraphError(f"node {node_id} reuses transcript evidence")
        _verify_reference(state, node_id, reference, indexes, refusals, requests)
        used.update(identifiers)
        references[node_id] = reference
    return references, _stored_references(state, False, used)


def validate_worker_evidence(state: dict[str, Any]) -> None:
    """Validate all stored worker evidence against native transcripts."""
    _stored_references(state, True)
