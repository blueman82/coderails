from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from graph_identity import GraphError, REFERENCE_KEYS, classify_worker_evidence, is_frozen_loop_evals, task_name
def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GraphError(f"{label} must be an object")
    return value
def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphError(f"{label} must be a non-empty string")
    return value
def _load(path: Path, label: str) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            return _object(json.load(handle), label)
    except (OSError, json.JSONDecodeError) as error:
        raise GraphError(f"{label} is missing or invalid: {error}") from error
def _records(path: Path, label: str) -> list[tuple[int, dict[str, Any]]]:
    records = []
    try:
        with path.open(encoding="utf-8") as transcript:
            for line_number, line in enumerate(transcript, 1):
                record = json.loads(line)
                records.append((line_number, _object(record, f"{label} line {line_number}")))
    except (OSError, json.JSONDecodeError) as error:
        raise GraphError(f"{label} is missing or invalid: {error}") from error
    if not records:
        raise GraphError(f"{label} is empty")
    return records
def _thread_transcript(thread_id: str) -> Path:
    root = Path.home() / ".codex" / "sessions"
    matches = list(root.rglob(f"*-{thread_id}.jsonl")) if root.is_dir() else []
    if len(matches) != 1:
        raise GraphError(f"thread {thread_id} must resolve to exactly one Codex transcript")
    first = _records(matches[0], f"thread {thread_id} transcript")[0][1]
    payload = first.get("payload")
    if first.get("type") != "session_meta" or not isinstance(payload, dict) or payload.get("id") != thread_id:
        raise GraphError(f"thread {thread_id} transcript has foreign session metadata")
    return matches[0]
def transcript_cursor(session_id: str) -> int:
    return len(_records(_thread_transcript(session_id), "parent transcript"))


def _payload(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload", record)
    return payload if isinstance(payload, dict) else {}


def _dispatch(record: dict[str, Any]) -> tuple[str, str, str, str] | None:
    payload = _payload(record)
    item = payload.get("item") if record.get("type") == "event_msg" else None
    if not isinstance(item, dict) or item.get("type") != "CollabAgentToolCall":
        return None
    dispatch_id, prompt = item.get("id"), item.get("prompt")
    receivers, agents = item.get("receiver_thread_ids"), item.get("receiver_agents")
    if (
        item.get("tool") != "spawn_agent"
        or item.get("status") != "completed"
        or not isinstance(dispatch_id, str)
        or not isinstance(prompt, str)
        or not isinstance(receivers, list)
        or len(receivers) != 1
        or not isinstance(receivers[0], str)
        or not isinstance(agents, list)
        or len(agents) != 1
        or not isinstance(agents[0], dict)
        or agents[0].get("thread_id") != receivers[0]
        or agents[0].get("agent_role") != "loop-worker"
        or not isinstance(agents[0].get("agent_nickname"), str)
    ):
        return None
    marker = prompt.split("\n", 1)[0]
    match = re.fullmatch(r"CODERAILS_GRAPH_TASK=(loop_worker_[0-9a-f]+(?:_a[2-9][0-9]*)?)", marker)
    if match is None:
        return None
    return dispatch_id, match.group(1), receivers[0], agents[0]["agent_nickname"]


def _child_terminal(parent_session: str, agent_thread_id: str, agent_nickname: str) -> str:
    records = _records(_thread_transcript(agent_thread_id), f"child {agent_thread_id} transcript")
    metadata = _payload(records[0][1])
    if (
        metadata.get("parent_thread_id") != parent_session
        or metadata.get("session_id") != parent_session
        or metadata.get("thread_source") != "subagent"
        or metadata.get("agent_nickname") != agent_nickname
        or metadata.get("agent_role") != "loop-worker"
    ):
        raise GraphError(f"child {agent_thread_id} belongs to a different graph dispatch")
    source = _object(metadata.get("source"), f"child {agent_thread_id}.source")
    spawn = _object(_object(source.get("subagent"), f"child {agent_thread_id}.source.subagent").get("thread_spawn"),
                    f"child {agent_thread_id}.source.subagent.thread_spawn")
    if (
        spawn.get("parent_thread_id") != parent_session
        or spawn.get("depth") != 1
        or spawn.get("agent_nickname") != agent_nickname
        or spawn.get("agent_role") != "loop-worker"
        or spawn.get("agent_path") is not None
    ):
        raise GraphError(f"child {agent_thread_id} has invalid graph dispatch metadata")
    started_at = records[0][1].get("timestamp")
    if not isinstance(started_at, str):
        raise GraphError(f"child {agent_thread_id} has invalid session metadata")
    events = [_payload(record) for _, record in records[1:]
              if isinstance(record.get("timestamp"), str) and record["timestamp"] >= started_at]
    terminals = [event for event in events if event.get("type") in {"task_complete", "turn_aborted"}]
    if not terminals or terminals[-1].get("type") != "task_complete":
        raise GraphError(f"child {agent_thread_id} did not finish successfully")
    turn_id = terminals[-1].get("turn_id")
    if not isinstance(turn_id, str):
        raise GraphError(f"child {agent_thread_id} has an invalid final task_complete")
    starts = [event for event in events if event.get("type") == "task_started" and event.get("turn_id") == turn_id]
    if len(starts) != 1 or sum(event.get("turn_id") == turn_id for event in terminals) != 1:
        raise GraphError(f"child {agent_thread_id} task_complete has no unique matching task_started")
    return turn_id
def _reference(value: Any, label: str) -> dict[str, Any]:
    reference = _object(value, label)
    if set(reference) != REFERENCE_KEYS or reference.get("kind") != "codex_agent":
        raise GraphError(f"{label} has invalid transcript reference fields")
    attempt = reference.get("attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise GraphError(f"{label}.attempt must be a positive integer")
    for key in REFERENCE_KEYS - {"kind", "attempt"}:
        _nonempty(reference.get(key), f"{label}.{key}")
    return reference
def _parent_indexes(
    records: list[tuple[int, dict[str, Any]]],
) -> dict[str, list[tuple[int, str, str, str]]]:
    spawns: dict[str, list[tuple[int, str, str, str]]] = {}
    for line_number, record in records:
        if dispatch := _dispatch(record):
            spawns.setdefault(dispatch[0], []).append((line_number, *dispatch[1:]))
    return spawns
def _verify_reference(
    state: dict[str, Any],
    node_id: str,
    reference: dict[str, Any],
    indexes: dict[str, list[tuple[int, str, str, str]]],
) -> int:
    spawns = indexes
    expected_task = task_name(node_id, reference["attempt"])
    call_id = reference["spawn_call_id"]
    if len(spawns.get(call_id, [])) != 1:
        raise GraphError(f"node {node_id} spawn reference is missing or duplicate")
    spawn_line, observed_task, observed_agent, nickname = spawns[call_id][0]
    if observed_task != expected_task or observed_agent != reference["agent_thread_id"]:
        raise GraphError(f"node {node_id} spawn reference has the wrong task")
    terminal = _child_terminal(state["session_id"], reference["agent_thread_id"], nickname)
    if terminal != reference["task_complete_turn_id"]:
        raise GraphError(f"node {node_id} task_complete reference does not match its child")
    return spawn_line
def _stored_references(state: dict[str, Any], require_complete: bool,
                       known_identifiers: set[str] | None = None) -> set[str]:
    indexes = _parent_indexes(_records(_thread_transcript(state["session_id"]), "parent transcript"))
    used = set(known_identifiers or ())
    waves: set[int] = set()
    ordinary: list[object] = []
    for node_id, node in state["graph"]["nodes"].items():
        if node_id in state["graph"]["joins"]:
            ordinary.extend(node["evidence"])
            continue
        references = []
        for index, item in enumerate(node["evidence"]):
            shaped, identifiers = classify_worker_evidence(item)
            if not shaped:
                ordinary.append(item)
                continue
            references.append((_reference(item, f"node {node_id}.evidence[{index}]"), identifiers))
        expected_count = node["retry"]["attempts"] + (1 if node["status"] in {"done", "skipped"} else 0)
        if sorted(item[0]["attempt"] for item in references) != list(range(1, expected_count + 1)):
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
            spawn_line = _verify_reference(state, node_id, reference, indexes)
            if spawn_line <= previous_line:
                raise GraphError(f"node {node_id} transcript attempts are stale or out of order")
            previous_line = spawn_line
    if waves:
        completion = state.get("completion") if state.get("status") == "complete" else None
        revision = completion.get("revision") if isinstance(completion, dict) else state["revision"]
        last_wave = revision - (2 if state["graph"]["active_wave"] is not None else 1)
        expected = set(range(last_wave - 2 * (len(waves) - 1), last_wave + 1, 2))
        if waves != expected:
            raise GraphError("stored worker wave evidence does not match graph revisions")
    if any(classify_worker_evidence(item, used)[0] for item in ordinary):
        raise GraphError("stored evidence contains noncanonical worker evidence")
    return used
def bind_worker_evidence(state: dict[str, Any], active_wave: dict[str, Any]
                         ) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Bind current-wave transcript records to each dispatched worker node."""
    used: set[str] = set()
    parent = _records(_thread_transcript(state["session_id"]), "parent transcript")
    indexes = _parent_indexes(parent)
    cursor = active_wave.get("transcript_cursor")
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 1:
        raise GraphError("active wave has no valid transcript cursor")
    references: dict[str, dict[str, Any]] = {}
    for node_id in active_wave["nodes"]:
        attempt = state["graph"]["nodes"][node_id]["retry"]["attempts"] + 1
        expected_task = task_name(node_id, attempt)
        matching = [(call_id, items[0]) for call_id, items in indexes.items()
                    if len(items) == 1 and items[0][0] > cursor
                    and items[0][1] == expected_task]
        if len(matching) != 1:
            raise GraphError(f"node {node_id} must have exactly one current-wave spawn")
        call_id, (_, _, agent_thread_id, nickname) = matching[0]
        terminal = _child_terminal(state["session_id"], agent_thread_id, nickname)
        reference = {
            "kind": "codex_agent",
            "attempt": attempt,
            "wave_id": active_wave["id"],
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
def _matching(evidence: dict[str, Any], state: dict[str, Any], label: str) -> None:
    if evidence.get("session_id") != state["session_id"] or evidence.get("loop_id") != state["loop_id"]:
        raise GraphError(f"{label} belongs to a different loop")
def _grading_checksum(evals: dict[str, Any], result: str) -> str:
    raw_evals = evals.get("evals")
    if not isinstance(raw_evals, list):
        raise GraphError("evals.evals must be an array")
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
        raise GraphError("evals are not scoped to this loop")
    if revision is not None and evals.get("revision") != revision:
        raise GraphError("evals revision does not match the graph")
    _nonempty(evals.get("verification_justification"), "evals.verification_justification")
    result = evals.get("result")
    if revision is None and is_frozen_loop_evals(evals):
        return
    if result not in {"GO", "VERIFICATION_LEVEL0"}:
        raise GraphError("evals are not graded GO")
    raw_evals = evals.get("evals")
    if not isinstance(raw_evals, list):
        raise GraphError("evals.evals must be an array")
    p0_statuses = [item.get("status") for item in raw_evals
                   if isinstance(item, dict) and item.get("priority") == "P0"]
    if result == "GO" and any(status != "pass" for status in p0_statuses):
        raise GraphError("evals result disagrees with its P0 statuses")
    if result == "VERIFICATION_LEVEL0" and (evals.get("verification_level") != 0 or raw_evals):
        raise GraphError("verification-level-0 result is invalid")
    grading = _object(evals.get("grading"), "evals.grading")
    if grading.get("by") != "post_evals.sh grade-loop":
        raise GraphError("evals grading stamp is missing")
    if grading.get("checksum") != _grading_checksum(evals, result):
        raise GraphError("evals grading checksum is invalid")
    amendments = evals.get("amendments")
    if not isinstance(amendments, list) or grading.get("amendments_at_grade") != len(amendments):
        raise GraphError("evals grading amendment count is stale")

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
        raise GraphError("proof evidence is missing or not passing")
    for index, raw_proof in enumerate(proofs):
        item = _object(raw_proof, f"proof.proofs[{index}]")
        if item.get("status") != "pass":
            raise GraphError("proof evidence is missing or not passing")
        _nonempty(item.get("id"), f"proof.proofs[{index}].id")
        _nonempty(item.get("cmd"), f"proof.proofs[{index}].cmd")
        _nonempty(item.get("evidence"), f"proof.proofs[{index}].evidence")
    _validate_observed_proofs(proofs, transcript_path, state["loop_id"])
    schema_version = retro.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or schema_version < 1:
        raise GraphError("retro evidence is incomplete")
    if retro.get("status") != "complete":
        raise GraphError("retro evidence is incomplete")

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
        raise GraphError("proof commands were not observed in this session")
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
            raise GraphError(f"proof command was unexecuted or last-failed: {command}")
