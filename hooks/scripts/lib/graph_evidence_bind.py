"""Derive graph evidence from native Claude dispatches, never caller assertions."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, cast

from .graph_evidence import check_record, child_identity, notifications, object_value, spawns, transcript
from .graph_executor import graph_contract
from .graph_scout_approval import approval

SKIP_PREFIXES = {"S2.5": "no_design_fork:", "S2.6": "no_retired_path:"}


def check_skip_wave(state: dict[str, Any], node_id: str, attempt: int, wave_id: str, cursor: int) -> None:
    """Require one unused issued scout slot and its independently captured wave boundary."""
    graph = state["graph"]
    dispatches = object_value(graph.get("dispatches"), "scout skip dispatches")
    records = ((identifier, object_value(record, "scout dispatch")) for identifier, record in dispatches.items())
    issued = [
        (identifier, record)
        for identifier, record in records
        if record.get("node_id") == node_id and record.get("wave_id") == wave_id
    ]
    if len(issued) != 1:
        raise ValueError("scout skip needs exactly one issued dispatch")
    identifier, record = issued[0]
    if (
        record.get("attempt") != attempt
        or type(record.get("attempt")) is not int
        or record.get("authorized") is not None
        or "authorized" not in record
        or identifier != graph_contract.dispatch_id(state["loop_id"], wave_id, node_id, attempt)
    ):
        raise ValueError("scout skip needs its unconsumed issued dispatch")
    history = object_value(graph.get("wave_history"), "native wave history")
    wave = object_value(history.get(wave_id), "native wave history entry")
    if (
        type(cursor) is not int
        or cursor < 0
        or type(wave.get("cursor")) is not int
        or wave["cursor"] != cursor
        or not isinstance(wave.get("nodes"), list)
        or node_id not in wave.get("nodes", [])
        or type(wave.get("revision")) is not int
        or type(record.get("revision")) is not int
        or wave["revision"] != record.get("revision")
    ):
        raise ValueError("scout skip no longer matches its native wave cursor or revision")


def provenance(value: object, depth: int = 0) -> bool:
    """Recognize nested or serialized provider identity claims."""
    if depth > 16:
        return True
    if isinstance(value, dict):
        if any(key in value for key in ("spawn_ref", "tool_use_id", "agent_id")):
            return True
        return any(provenance(item, depth + 1) for item in cast(dict[str, object], value).values())
    if isinstance(value, list):
        return any(provenance(item, depth + 1) for item in cast(list[object], value))
    if isinstance(value, str):
        normalized = re.sub(r"[^a-z_]", "", value.lower())
        if "claude_agent" in normalized or "graph_skip" in normalized or "toolu_" in value:
            return True
        try:
            decoded: object = json.loads(value)
        except ValueError:
            return False
        return provenance(decoded, depth + 1)
    return False


def terminal(spawn: dict[str, Any], notices: dict[str, list[dict[str, str]]], agent: str) -> None:
    """Require an unambiguous successful native terminal notification."""
    values = notices.get(spawn["tool_use_id"], [])
    if not values or any(
        value["status"] != "completed" or not value["result"].strip() or value["task-id"] != agent for value in values
    ):
        raise ValueError("no unambiguous completed notification for native child")


def used_references(state: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Collect already-bound tool and child identities to reject reuse."""
    tools: set[str] = set()
    agents: set[str] = set()
    for node in state["graph"]["nodes"].values():
        for item in node["evidence"]:
            if not isinstance(item, dict):
                if provenance(item):
                    raise ValueError("stored evidence contains malformed native provenance")
                continue
            item = cast(dict[str, Any], item)
            if item.get("kind") == "graph_skip":
                continue
            if item.get("kind") != "claude_agent" or any(
                provenance(cast(object, value)) for value in item.values() if isinstance(value, (dict, list))
            ):
                if provenance(item):
                    raise ValueError("stored evidence contains malformed native provenance")
                continue
            for key, seen in (("tool_use_id", tools), ("agent_id", agents)):
                value = item.get(key)
                if isinstance(value, str) and value:
                    if value in seen:
                        raise ValueError("native identity is already bound more than once")
                    seen.add(value)
    return tools, agents


def bind_wave(state: dict[str, Any], results: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Bind every dispatched node to its actual current-wave native workers."""
    active = object_value(state["graph"]["active_wave"], "active wave")
    boundary = active.get("transcript_cursor")
    if type(boundary) is not int or boundary < 0:
        raise ValueError("active wave lacks a native transcript cursor")
    session = state["session_id"]
    path = transcript(session)
    rows, notices = spawns(path, session), notifications(path, session)
    tools, agents = used_references(state)
    bound: dict[str, list[dict[str, Any]]] = {}
    ids: set[str] = set()
    for node_id, result in results.items():
        result = object_value(result, "wave result")
        if provenance(result.get("evidence")):
            raise ValueError("caller evidence must not assert native worker provenance")
        candidates = [
            row
            for row in rows
            if row["node_id"] == node_id and row["wave_id"] == active["wave_id"] and row["line"] > boundary
        ]
        node = state["graph"]["nodes"][node_id]
        evidence = result["evidence"]
        if result["outcome"] == "skipped" and isinstance(evidence, str):
            approved = evidence.startswith("non_independent:")
            prefix = "non_independent:" if approved else SKIP_PREFIXES.get(node_id)
            if prefix and evidence.startswith(prefix):
                if not evidence[len(prefix) :].strip() or node["respawn"]["generation"]:
                    raise ValueError("scout skip needs a reason and no stale attempt")
                if candidates:
                    raise ValueError("scout skip cannot reuse a native spawn")
                attempt = node["retry"]["attempts"] + 1
                if approved:
                    if not evidence.startswith("non_independent: human approved") or attempt < 2:
                        raise ValueError("non-independent skip needs a prior refusal and explicit approval")
                    approval_ref = approval(state, node_id, attempt, rows, active["wave_id"], boundary)
                else:
                    if attempt != 1:
                        raise ValueError("no-work scout skip must precede any scout attempt")
                    approval_ref = {}
                check_skip_wave(state, node_id, attempt, active["wave_id"], boundary)
                wave = state["graph"]["wave_history"][active["wave_id"]]
                if (
                    active.get("revision") != state["revision"]
                    or wave["revision"] != active["revision"]
                    or wave["nodes"] != active["nodes"]
                ):
                    raise ValueError("scout skip does not own the active wave")
                bound[node_id] = [
                    {
                        "kind": "graph_skip",
                        "attempt": attempt,
                        "wave_id": active["wave_id"],
                        "reason": prefix[:-1],
                        "evidence_sha256": hashlib.sha256(evidence.encode()).hexdigest(),
                        "cursor": boundary,
                        **approval_ref,
                    }
                ]
                continue
        if not candidates:
            raise ValueError(f"node {node_id} has no native spawn after the wave cursor")
        attempt = node["retry"]["attempts"] + node["respawn"]["generation"] + 1
        references: list[dict[str, Any]] = []
        for row in candidates:
            if any(row[key] != state[key] for key in ("session_id", "loop_id", "revision")):
                raise ValueError("native spawn envelope does not own this session/loop/revision")
            check_record(state, row)
            if "dispatch_id" in row:
                if row["dispatch_id"] in ids:
                    raise graph_contract.DispatchDeniedError("dispatch_replayed", "two spawns carry one dispatch id")
                ids.add(row["dispatch_id"])
            tool = row["tool_use_id"]
            if tool in tools:
                raise ValueError("native tool identity has already been bound")
            completed = result["outcome"] == "done"
            agent = child_identity(path, session, row, completed, result["outcome"] == "failed")
            if agent and agent in agents:
                raise ValueError("native child identity has already been bound")
            if completed:
                terminal(row, notices, agent)
            reference = {
                "kind": "claude_agent",
                "attempt": attempt,
                "wave_id": active["wave_id"],
                "tool_use_id": tool,
                "record_uuid": row["record_uuid"],
                "subagent_type": row["subagent_type"],
                "outcome": result["outcome"],
            }
            if agent:
                reference["agent_id"] = agent
                agents.add(agent)
            tools.add(tool)
            references.append(reference)
        bound[node_id] = references
    return bound
