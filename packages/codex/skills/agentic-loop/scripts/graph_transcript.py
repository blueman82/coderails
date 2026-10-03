"""Validate provider-native parent dispatch and child transcript identities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from graph_data import event_payload, object_value, read_records
from graph_identity import GraphError, task_node


def thread_transcript(thread_id: str) -> Path:
    """Locate a unique transcript for one native thread identity."""
    root = Path.home() / ".codex" / "sessions"
    matches = list(root.rglob(f"*-{thread_id}.jsonl")) if root.is_dir() else []
    if len(matches) != 1:
        raise GraphError(f"thread {thread_id} must resolve to exactly one Codex transcript")
    first = read_records(matches[0], f"thread {thread_id} transcript")[0][1]
    payload = first.get("payload")
    if first.get("type") != "session_meta" or not isinstance(payload, dict):
        raise GraphError(f"thread {thread_id} transcript has foreign session metadata")
    payload = cast(dict[str, Any], payload)
    if payload.get("id") != thread_id:
        raise GraphError(f"thread {thread_id} transcript has foreign session metadata")
    return matches[0]


def transcript_cursor(session_id: str) -> int:
    """Return the current native transcript record count for a session."""
    return len(read_records(thread_transcript(session_id), "parent transcript"))


def _canonical_task(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        task_node(value)
    except GraphError:
        return None
    return value


def _legacy_dispatch(record: dict[str, Any]) -> tuple[str, str, str, str, str | None, str | None] | None:
    payload = event_payload(record)
    raw_item = payload.get("item") if record.get("type") == "event_msg" else None
    if not isinstance(raw_item, dict):
        return None
    item = cast(dict[str, Any], raw_item)
    if item.get("type") != "CollabAgentToolCall":
        return None
    dispatch_id, prompt = item.get("id"), item.get("prompt")
    receivers, agents = item.get("receiver_thread_ids"), item.get("receiver_agents")
    if (
        item.get("tool") != "spawn_agent"
        or item.get("status") != "completed"
        or not isinstance(dispatch_id, str)
        or not isinstance(prompt, str)
        or not isinstance(receivers, list)
        or not isinstance(agents, list)
    ):
        return None
    receivers, agents = cast(list[object], receivers), cast(list[object], agents)
    if len(receivers) != 1 or not isinstance(receivers[0], str) or len(agents) != 1 or not isinstance(agents[0], dict):
        return None
    agent = cast(dict[str, Any], agents[0])
    if (
        agent.get("thread_id") != receivers[0]
        or not isinstance(agent.get("agent_role"), str)
        or not agent["agent_role"].strip()
        or not isinstance(agent.get("agent_nickname"), str)
    ):
        return None
    task = _canonical_task(prompt.split("\n", 1)[0].removeprefix("CODERAILS_GRAPH_TASK="))
    if task is None:
        return None
    return dispatch_id, task, receivers[0], agent["agent_nickname"], None, agent["agent_role"]


def _native_function_call(record: dict[str, Any]) -> tuple[str, str, str | None] | None:
    if record.get("type") != "response_item":
        return None
    item = event_payload(record)
    if item.get("type") != "function_call" or item.get("name") != "spawn_agent":
        return None
    call_id, arguments = item.get("call_id"), item.get("arguments")
    if not isinstance(call_id, str) or not isinstance(arguments, str):
        return None
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    parsed_object = cast(dict[str, Any], parsed)
    if "agent_type" in parsed_object:
        if not isinstance(parsed_object["agent_type"], str) or not parsed_object["agent_type"].strip():
            return None
        expected_role = parsed_object["agent_type"]
    elif item.get("namespace") == "collaboration":
        expected_role = None
    else:
        return None
    task = _canonical_task(parsed_object.get("task_name"))
    return (call_id, task, expected_role) if task is not None else None


def _native_activity(record: dict[str, Any]) -> tuple[str, str, str] | None:
    payload = event_payload(record)
    item = payload.get("item") if record.get("type") == "event_msg" else None
    if not isinstance(item, dict):
        return None
    item = cast(dict[str, Any], item)
    call_id, agent_thread_id, agent_path = item.get("id"), item.get("agent_thread_id"), item.get("agent_path")
    if (
        item.get("type") != "SubAgentActivity"
        or item.get("kind") != "started"
        or not isinstance(call_id, str)
        or not isinstance(agent_thread_id, str)
        or not isinstance(agent_path, str)
    ):
        return None
    return call_id, agent_thread_id, agent_path


def child_read_records(
    parent_session: str,
    agent_thread_id: str,
    agent_nickname: str | None,
    expected_path: str | None,
    expected_role: str | None,
) -> list[tuple[int, dict[str, Any]]]:
    """Read a child transcript and validate its native dispatch ownership."""
    records = read_records(thread_transcript(agent_thread_id), f"child {agent_thread_id} transcript")
    metadata = event_payload(records[0][1])
    if (
        metadata.get("parent_thread_id") != parent_session
        or metadata.get("session_id") != parent_session
        or metadata.get("thread_source") != "subagent"
        or (agent_nickname is not None and metadata.get("agent_nickname") != agent_nickname)
        or ("agent_role" not in metadata and (expected_role is not None or expected_path is None))
        or metadata.get("agent_role") != expected_role
        or ("agent_path" in metadata and metadata["agent_path"] != expected_path)
    ):
        raise GraphError(f"child {agent_thread_id} belongs to a different graph dispatch")
    source = object_value(metadata.get("source"), f"child {agent_thread_id}.source")
    spawn = object_value(
        object_value(source.get("subagent"), f"child {agent_thread_id}.source.subagent").get("thread_spawn"),
        f"child {agent_thread_id}.source.subagent.thread_spawn",
    )
    if (
        spawn.get("parent_thread_id") != parent_session
        or spawn.get("depth") != 1
        or (agent_nickname is not None and spawn.get("agent_nickname") != agent_nickname)
        or "agent_role" not in spawn
        or spawn.get("agent_role") != expected_role
        or spawn.get("agent_path") != expected_path
    ):
        raise GraphError(f"child {agent_thread_id} has invalid graph dispatch metadata")
    return records


def child_terminal(
    parent_session: str,
    agent_thread_id: str,
    agent_nickname: str | None,
    expected_path: str | None,
    expected_role: str | None,
    turn_id: str | None = None,
) -> str:
    """Require a uniquely started successful turn, and a successful latest child activity.

    Without `turn_id` the final terminal turn is returned. With it, that earlier recorded turn is accepted
    only if it is a uniquely started task_complete and the child's latest lifecycle event is a task_complete.
    """
    records = child_read_records(parent_session, agent_thread_id, agent_nickname, expected_path, expected_role)
    started_at = records[0][1].get("timestamp")
    if not isinstance(started_at, str):
        raise GraphError(f"child {agent_thread_id} has invalid session metadata")
    events = [
        event_payload(record)
        for _, record in records[1:]
        if isinstance(record.get("timestamp"), str) and record["timestamp"] >= started_at
    ]
    lifecycle = [event for event in events if event.get("type") in {"task_started", "task_complete", "turn_aborted"}]
    if not lifecycle or lifecycle[-1].get("type") != "task_complete":
        raise GraphError(f"child {agent_thread_id} did not finish successfully")
    terminals = [event for event in lifecycle if event.get("type") != "task_started"]
    turn_id = turn_id if turn_id is not None else terminals[-1].get("turn_id")
    if not isinstance(turn_id, str):
        raise GraphError(f"child {agent_thread_id} has an invalid final task_complete")
    starts = [
        i
        for i, event in enumerate(lifecycle)
        if event.get("type") == "task_started" and event.get("turn_id") == turn_id
    ]
    ends = [
        i
        for i, event in enumerate(lifecycle)
        if event.get("type") != "task_started" and event.get("turn_id") == turn_id
    ]
    if (
        len(starts) != 1
        or len(ends) != 1
        or lifecycle[ends[0]].get("type") != "task_complete"
        or starts[0] > ends[0]
        or any(event.get("type") == "task_started" for event in lifecycle[starts[0] + 1 : ends[0]])
    ):
        raise GraphError(f"child {agent_thread_id} task_complete has no unique matching task_started")
    return turn_id


def parent_indexes(
    records: list[tuple[int, dict[str, Any]]],
) -> dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]]:
    """Index legacy dispatches and native function-call/activity joins."""
    spawns: dict[str, list[tuple[int, str, str, str | None, str | None, str | None]]] = {}
    native_calls: dict[str, list[tuple[int, str, str | None]]] = {}
    call_counts: dict[str, int] = {}
    native_activities: dict[str, list[tuple[int, str, str]]] = {}
    for line_number, record in records:
        item = event_payload(record)
        if record.get("type") == "response_item" and item.get("type") == "function_call":
            call_id = item.get("call_id")
            if isinstance(call_id, str):
                call_counts[call_id] = call_counts.get(call_id, 0) + 1
        if dispatch := _legacy_dispatch(record):
            spawns.setdefault(dispatch[0], []).append((line_number, *dispatch[1:]))
        if call := _native_function_call(record):
            native_calls.setdefault(call[0], []).append((line_number, *call[1:]))
        if activity := _native_activity(record):
            native_activities.setdefault(activity[0], []).append((line_number, *activity[1:]))
    for call_id, calls in native_calls.items():
        activities = native_activities.get(call_id, [])
        if len(calls) != 1 or call_counts[call_id] != 1 or len(activities) != 1:
            continue
        call_line, observed_task, expected_role = calls[0]
        for activity_line, agent_thread_id, agent_path in activities:
            if activity_line <= call_line or agent_path != f"/root/{observed_task}":
                continue
            spawns.setdefault(call_id, []).append(
                (call_line, observed_task, agent_thread_id, None, agent_path, expected_role)
            )
    return spawns


def _error_shaped(output: object) -> bool:
    """Codex spawn errors are plain text; a success result is a JSON object such as {"task_name": ...}."""
    if not isinstance(output, str) or not output.strip():
        return False
    try:
        return not isinstance(json.loads(output), dict)
    except ValueError:
        return True


def refused_launches(records: list[tuple[int, dict[str, Any]]]) -> dict[str, tuple[int, str]]:
    """Index native spawn_agent calls answered by an output but never backed by any SubAgentActivity."""
    calls: dict[str, list[tuple[int, str]]] = {}
    call_counts: dict[str, int] = {}
    outputs: dict[str, int] = {}
    activities: set[str] = set()
    for line_number, record in records:
        item = event_payload(record)
        if record.get("type") == "response_item" and item.get("type") == "function_call":
            call_id = item.get("call_id")
            if isinstance(call_id, str):
                call_counts[call_id] = call_counts.get(call_id, 0) + 1
            if call := _native_function_call(record):
                calls.setdefault(call[0], []).append((line_number, call[1]))
        elif record.get("type") == "response_item" and item.get("type") == "function_call_output":
            if isinstance(item.get("call_id"), str) and _error_shaped(item.get("output")):
                outputs.setdefault(item["call_id"], line_number)
        elif record.get("type") == "event_msg":
            nested = item.get("item")
            if isinstance(nested, dict) and cast(dict[str, Any], nested).get("type") == "SubAgentActivity":
                activities.add(str(cast(dict[str, Any], nested).get("id")))
    return {
        call_id: rows[0]
        for call_id, rows in calls.items()
        if len(rows) == 1
        and call_counts[call_id] == 1
        and call_id not in activities
        and outputs.get(call_id, 0) > rows[0][0]
    }
