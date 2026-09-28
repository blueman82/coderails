"""Derive graph evidence from native Claude dispatches, never caller assertions."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from .graph_evidence import child_identity, notifications, object_value, spawns, transcript


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
        if "claude_agent" in normalized or "toolu_" in value:
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
    for node_id, result in results.items():
        if provenance(result.get("evidence")):
            raise ValueError("caller evidence must not assert native worker provenance")
        candidates = [
            row
            for row in rows
            if row["node_id"] == node_id and row["wave_id"] == active["wave_id"] and row["line"] > boundary
        ]
        if not candidates:
            raise ValueError(f"node {node_id} has no native spawn after the wave cursor")
        node = state["graph"]["nodes"][node_id]
        attempt = node["retry"]["attempts"] + node["respawn"]["generation"] + 1
        references: list[dict[str, Any]] = []
        for row in candidates:
            if any(row[key] != state[key] for key in ("session_id", "loop_id", "revision")):
                raise ValueError("native spawn envelope does not own this session/loop/revision")
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
