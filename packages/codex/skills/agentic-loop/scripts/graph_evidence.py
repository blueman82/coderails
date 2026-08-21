from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from graph_identity import task_name


class EvidenceError(ValueError):
    pass

def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be an object")
    return value

def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(f"{label} must be a non-empty string")
    return value

def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return _object(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is missing or invalid: {error}") from error

def _records(path: Path, label: str) -> list[tuple[int, dict[str, Any]]]:
    records = []
    try:
        with path.open(encoding="utf-8") as transcript:
            for line_number, line in enumerate(transcript, 1):
                record = json.loads(line)
                records.append((line_number, _object(record, f"{label} line {line_number}")))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"{label} is missing or invalid: {error}") from error
    if not records:
        raise EvidenceError(f"{label} is empty")
    return records

def _thread_transcript(thread_id: str) -> Path:
    root = Path.home() / ".codex" / "sessions"
    matches = list(root.rglob(f"*-{thread_id}.jsonl")) if root.is_dir() else []
    if len(matches) != 1:
        raise EvidenceError(f"thread {thread_id} must resolve to exactly one Codex transcript")
    first = _records(matches[0], f"thread {thread_id} transcript")[0][1]
    payload = first.get("payload")
    if first.get("type") != "session_meta" or not isinstance(payload, dict) or payload.get("id") != thread_id:
        raise EvidenceError(f"thread {thread_id} transcript has foreign session metadata")
    return matches[0]

def transcript_cursor(session_id: str) -> int:
    return len(_records(_thread_transcript(session_id), "parent transcript"))

def _payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload", record)
    return payload if isinstance(payload, dict) else {}

def _spawn(payload: dict[str, Any]) -> tuple[str, str] | None:
    if payload.get("type") != "function_call" or payload.get("name") != "spawn_agent":
        return None
    arguments = payload.get("arguments")
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except json.JSONDecodeError:
        return None
    call_id = payload.get("call_id")
    if isinstance(parsed, dict) and isinstance(call_id, str) and isinstance(parsed.get("task_name"), str):
        return call_id, parsed["task_name"]
    return None

def _spawn_result(payload: dict[str, Any]) -> tuple[str, str] | None:
    if payload.get("type") != "function_call_output":
        return None
    call_id, output = payload.get("call_id"), payload.get("output")
    if not isinstance(call_id, str) or not isinstance(output, str):
        return None
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and isinstance(parsed.get("task_name"), str):
        return call_id, parsed["task_name"]
    return None

def _activity(record: dict[str, Any]) -> dict[str, Any] | None:
    payload = _payload(record)
    item = payload.get("item") if record.get("type") == "event_msg" else None
    return item if isinstance(item, dict) and item.get("type") == "SubAgentActivity" else None

def _child_terminal(parent_session: str, expected_task: str, agent_thread_id: str) -> str:
    records = _records(_thread_transcript(agent_thread_id), f"child {agent_thread_id} transcript")
    metadata = _payload(records[0][1])
    if (
        metadata.get("parent_thread_id") != parent_session
        or metadata.get("session_id") != parent_session
        or metadata.get("thread_source") != "subagent"
        or metadata.get("agent_path") != f"/root/{expected_task}"
    ):
        raise EvidenceError(f"child {agent_thread_id} belongs to a different graph dispatch")
    started_at = records[0][1].get("timestamp")
    if not isinstance(started_at, str):
        raise EvidenceError(f"child {agent_thread_id} has invalid session metadata")
    events = [_payload(record) for _, record in records[1:]
              if isinstance(record.get("timestamp"), str) and record["timestamp"] >= started_at]
    if any(event.get("type") == "turn_aborted" for event in events):
        raise EvidenceError(f"child {agent_thread_id} did not complete successfully")
    completed = [event for event in events if event.get("type") == "task_complete"]
    if len(completed) != 1 or not isinstance(completed[0].get("turn_id"), str):
        raise EvidenceError(f"child {agent_thread_id} must have exactly one successful task_complete")
    turn_id = completed[0]["turn_id"]
    starts = [event for event in events if event.get("type") == "task_started" and event.get("turn_id") == turn_id]
    if len(starts) != 1:
        raise EvidenceError(f"child {agent_thread_id} task_complete has no matching task_started")
    return turn_id


REFERENCE_KEYS = {"kind", "attempt", "wave_id", "spawn_call_id", "agent_thread_id",
                  "task_complete_turn_id"}

def _reference(value: Any, label: str) -> dict[str, Any]:
    reference = _object(value, label)
    if set(reference) != REFERENCE_KEYS or reference.get("kind") != "codex_agent":
        raise EvidenceError(f"{label} has invalid transcript reference fields")
    attempt = reference.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise EvidenceError(f"{label}.attempt must be a positive integer")
    for key in REFERENCE_KEYS - {"kind", "attempt"}:
        _nonempty(reference.get(key), f"{label}.{key}")
    return reference

def _parent_indexes(
    records: list[tuple[int, dict[str, Any]]],
) -> tuple[dict[str, list[tuple[int, str]]], dict[str, list[str]],
           dict[str, list[dict[str, Any]]]]:
    spawns: dict[str, list[tuple[int, str]]] = {}
    results: dict[str, list[str]] = {}
    activities: dict[str, list[dict[str, Any]]] = {}
    for line_number, record in records:
        payload = _payload(record)
        if spawn := _spawn(payload):
            spawns.setdefault(spawn[0], []).append((line_number, spawn[1]))
        if result := _spawn_result(payload):
            results.setdefault(result[0], []).append(result[1])
        if activity := _activity(record):
            call_id = activity.get("id")
            if isinstance(call_id, str):
                activities.setdefault(call_id, []).append(activity)
    return spawns, results, activities

def _verify_reference(
    state: dict[str, Any],
    node_id: str,
    reference: dict[str, Any],
    indexes: tuple[dict[str, list[tuple[int, str]]], dict[str, list[str]], dict[str, list[dict[str, Any]]]],
) -> int:
    spawns, results, activities = indexes
    expected_task = task_name(node_id)
    call_id = reference["spawn_call_id"]
    if len(spawns.get(call_id, [])) != 1:
        raise EvidenceError(f"node {node_id} spawn reference is missing or duplicate")
    spawn_line, observed_task = spawns[call_id][0]
    if observed_task != expected_task or results.get(call_id) != [f"/root/{expected_task}"]:
        raise EvidenceError(f"node {node_id} spawn reference has the wrong task")
    activity_items = activities.get(call_id, [])
    if len(activity_items) != 1:
        raise EvidenceError(f"node {node_id} SubAgentActivity is missing or duplicate")
    activity = activity_items[0]
    if (
        activity.get("kind") != "started"
        or activity.get("agent_path") != f"/root/{expected_task}"
        or activity.get("agent_thread_id") != reference["agent_thread_id"]
    ):
        raise EvidenceError(f"node {node_id} SubAgentActivity does not match its spawn")
    terminal = _child_terminal(state["session_id"], expected_task, reference["agent_thread_id"])
    if terminal != reference["task_complete_turn_id"]:
        raise EvidenceError(f"node {node_id} task_complete reference does not match its child")
    return spawn_line

def _stored_references(state: dict[str, Any], require_complete: bool) -> set[str]:
    parent = _records(_thread_transcript(state["session_id"]), "parent transcript")
    indexes = _parent_indexes(parent)
    joins = state["graph"]["joins"]
    used: set[str] = set()
    for node_id, node in state["graph"]["nodes"].items():
        if node_id in joins:
            continue
        references = [_reference(item, f"node {node_id}.evidence[{index}]")
                      for index, item in enumerate(node["evidence"])
                      if isinstance(item, dict) and item.get("kind") == "codex_agent"]
        expected_count = node["retry"]["attempts"] + (1 if node["status"] in {"done", "skipped"} else 0)
        if len(references) != expected_count or sorted(item["attempt"] for item in references) != list(range(1, expected_count + 1)):
            raise EvidenceError(f"node {node_id} transcript attempts do not match its graph state")
        if require_complete and node["status"] not in {"done", "skipped"}:
            raise EvidenceError(f"node {node_id} has no completed transcript-backed attempt")
        previous_line = 0
        for reference in sorted(references, key=lambda item: item["attempt"]):
            identifiers = {reference["spawn_call_id"], reference["agent_thread_id"],
                           reference["task_complete_turn_id"]}
            if used & identifiers:
                raise EvidenceError(f"node {node_id} reuses transcript evidence")
            used.update(identifiers)
            spawn_line = _verify_reference(state, node_id, reference, indexes)
            if spawn_line <= previous_line:
                raise EvidenceError(f"node {node_id} transcript attempts are stale or out of order")
            previous_line = spawn_line
    return used

def bind_worker_evidence(state: dict[str, Any], active_wave: dict[str, Any]) -> dict[str, dict[str, Any]]:
    used = _stored_references(state, False)
    parent = _records(_thread_transcript(state["session_id"]), "parent transcript")
    indexes = _parent_indexes(parent)
    cursor = active_wave.get("transcript_cursor")
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 1:
        raise EvidenceError("active wave has no valid transcript cursor")
    references: dict[str, dict[str, Any]] = {}
    for node_id in active_wave["nodes"]:
        expected_task = task_name(node_id)
        matching = [(call_id, items[0][0]) for call_id, items in indexes[0].items()
                    if len(items) == 1 and items[0][0] > cursor
                    and items[0][1] == expected_task]
        if len(matching) != 1:
            raise EvidenceError(f"node {node_id} must have exactly one current-wave spawn")
        call_id, _ = matching[0]
        activity_items = indexes[2].get(call_id, [])
        if len(activity_items) != 1 or not isinstance(activity_items[0].get("agent_thread_id"), str):
            raise EvidenceError(f"node {node_id} SubAgentActivity is missing or duplicate")
        agent_thread_id = activity_items[0]["agent_thread_id"]
        terminal = _child_terminal(state["session_id"], expected_task, agent_thread_id)
        reference = {
            "kind": "codex_agent",
            "attempt": state["graph"]["nodes"][node_id]["retry"]["attempts"] + 1,
            "wave_id": active_wave["id"],
            "spawn_call_id": call_id,
            "agent_thread_id": agent_thread_id,
            "task_complete_turn_id": terminal,
        }
        identifiers = {call_id, agent_thread_id, terminal}
        if used & identifiers:
            raise EvidenceError(f"node {node_id} reuses transcript evidence")
        _verify_reference(state, node_id, reference, indexes)
        used.update(identifiers)
        references[node_id] = reference
    return references

def validate_worker_evidence(state: dict[str, Any]) -> None:
    _stored_references(state, True)

def _matching(evidence: dict[str, Any], state: dict[str, Any], label: str) -> None:
    if evidence.get("session_id") != state["session_id"] or evidence.get("loop_id") != state["loop_id"]:
        raise EvidenceError(f"{label} belongs to a different loop")

def _grading_checksum(evals: dict[str, Any], result: str) -> str:
    raw_evals = evals.get("evals")
    if not isinstance(raw_evals, list):
        raise EvidenceError("evals.evals must be an array")
    canonical = []
    for index, raw_eval in enumerate(raw_evals):
        item = _object(raw_eval, f"evals.evals[{index}]")
        canonical.append({key: item.get(key) for key in ("id", "priority", "status")})
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(f"{encoded}\n{result}".encode()).hexdigest()

def validate_evals(state: dict[str, Any], revision: int | None, path: Path) -> None:
    evals = _load(path, "evals")
    _matching(evals, state, "evals")
    if evals.get("scope") != "loop" or evals.get("task_ref") != state["loop_id"]:
        raise EvidenceError("evals are not scoped to this loop")
    if revision is not None and evals.get("revision") != revision:
        raise EvidenceError("evals revision does not match the graph")
    _nonempty(evals.get("verification_justification"), "evals.verification_justification")
    result = evals.get("result")
    if result not in {"GO", "VERIFICATION_LEVEL0"}:
        raise EvidenceError("evals are not graded GO")
    raw_evals = evals.get("evals")
    if not isinstance(raw_evals, list):
        raise EvidenceError("evals.evals must be an array")
    p0_statuses = [item.get("status") for item in raw_evals
                   if isinstance(item, dict) and item.get("priority") == "P0"]
    if result == "GO" and any(status != "pass" for status in p0_statuses):
        raise EvidenceError("evals result disagrees with its P0 statuses")
    if result == "VERIFICATION_LEVEL0" and (evals.get("verification_level") != 0 or raw_evals):
        raise EvidenceError("verification-level-0 result is invalid")
    grading = _object(evals.get("grading"), "evals.grading")
    if grading.get("by") != "post_evals.sh grade-loop":
        raise EvidenceError("evals grading stamp is missing")
    if grading.get("checksum") != _grading_checksum(evals, result):
        raise EvidenceError("evals grading checksum is invalid")
    amendments = evals.get("amendments")
    if not isinstance(amendments, list) or grading.get("amendments_at_grade") != len(amendments):
        raise EvidenceError("evals grading amendment count is stale")

def validate_completion_evidence(
    state: dict[str, Any],
    revision: int,
    evals_path: Path,
    proof_path: Path,
    retro_path: Path,
    transcript_path: Path | None,
) -> None:
    proof = _load(proof_path, "proof")
    retro = _load(retro_path, "retro")
    for label, evidence in (("proof", proof), ("retro", retro)):
        _matching(evidence, state, label)
    validate_evals(state, revision, evals_path)
    proofs = proof.get("proofs")
    if not isinstance(proofs, list) or not proofs:
        raise EvidenceError("proof evidence is missing or not passing")
    for index, raw_proof in enumerate(proofs):
        item = _object(raw_proof, f"proof.proofs[{index}]")
        if item.get("status") != "pass":
            raise EvidenceError("proof evidence is missing or not passing")
        _nonempty(item.get("id"), f"proof.proofs[{index}].id")
        _nonempty(item.get("cmd"), f"proof.proofs[{index}].cmd")
        _nonempty(item.get("evidence"), f"proof.proofs[{index}].evidence")
    _validate_observed_proofs(proofs, transcript_path, state["loop_id"])
    schema_version = retro.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise EvidenceError("retro evidence is incomplete")
    if retro.get("status") != "complete":
        raise EvidenceError("retro evidence is incomplete")

def _exec_command(payload: dict[str, Any]) -> tuple[str, str] | None:
    if payload.get("type") == "function_call" and payload.get("name") == "exec_command":
        arguments = payload.get("arguments")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict) and isinstance(parsed.get("cmd"), str):
            return str(payload.get("call_id", "")), parsed["cmd"].strip()
    if payload.get("type") == "custom_tool_call" and payload.get("name") == "exec":
        source = payload.get("input")
        if not isinstance(source, str) or "tools.exec_command" not in source:
            return None
        match = re.search(r'\bcmd\s*:\s*("(?:\\.|[^"\\])*")', source)
        if match:
            return str(payload.get("call_id", "")), json.loads(match.group(1)).strip()
    return None

def _exec_result(payload: dict[str, Any]) -> tuple[str, bool, str | None] | None:
    if payload.get("type") not in {"function_call_output", "custom_tool_call_output"}:
        return None
    call_id = payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        return None
    output = payload.get("output")
    if isinstance(output, list):
        output = "".join(
            item.get("text", "")
            for item in output
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    if not isinstance(output, str):
        return call_id, False, None
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return call_id, False, None
    if not isinstance(parsed, dict):
        return call_id, False, None
    exit_code = parsed.get("exit_code")
    passed = isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code == 0
    result_loop = parsed.get("loop_id")
    if "loop_id" in parsed and not isinstance(result_loop, str):
        passed = False
    return call_id, passed, result_loop if isinstance(result_loop, str) else None

def _validate_observed_proofs(proofs: list[Any], transcript_path: Path | None, loop_id: str) -> None:
    if transcript_path is None:
        raise EvidenceError("proof commands were not observed in this session")
    calls: list[tuple[str, str, str | None]] = []
    results: dict[str, tuple[bool, str | None]] = {}
    transcript_loop: str | None = None
    for _, record in _records(transcript_path, "proof transcript"):
        if record.get("type") == "turn_context":
            context = record.get("payload")
            if isinstance(context, dict) and "loop_id" in context:
                observed_loop = context["loop_id"]
                transcript_loop = observed_loop if isinstance(observed_loop, str) else ""
            continue
        payload = _payload(record)
        if call := _exec_command(payload):
            calls.append((*call, transcript_loop))
        if result := _exec_result(payload):
            results[result[0]] = (result[1], result[2])
    for raw_proof in proofs:
        command = raw_proof["cmd"].strip()
        matching = [
            call_id
            for call_id, observed, observed_loop in calls
            if observed == command and observed_loop in {None, loop_id}
        ]
        result = results.get(matching[-1]) if matching else None
        if result is None or result[0] is not True or result[1] not in {None, loop_id}:
            raise EvidenceError(f"proof command was unexecuted or last-failed: {command}")
