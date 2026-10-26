"""Derive graph evidence from native Claude dispatches, never caller assertions."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from .graph_evidence import child_identity, notifications, object_value, spawns, transcript
from .graph_executor import graph_contract


def check_record(state: dict[str, Any], row: dict[str, Any]) -> None:
    """A spawn in a wave at or after contract_from_revision must match its begin-wave record and sections digest."""
    start = state["graph"].get("contract_from_revision")
    if type(start) is not int or row["revision"] < start:
        return  # history from before the dispatch contract (the converter stamps the first contract revision)
    if "dispatch_id" not in row:
        raise graph_contract.DispatchDeniedError(
            "dispatch_missing_envelope", "native spawn lacks a v2 dispatch envelope"
        )
    if graph_contract.dispatch_off():
        graph_contract.check_ownership(state, row, live=False)
        return
    record = graph_contract.check_dispatch(state, row, row["prompt"], live=False)
    graph_contract.assert_role(record["contract"], row["subagent_type"], "coderails:", graph_contract.CLAUDE_TYPES)
    authorized: object = record.get("authorized")
    authorized = cast(dict[str, Any], authorized) if isinstance(authorized, dict) else None
    if not isinstance(authorized, dict) or (
        authorized.get("tool_use_id") is not None and authorized.get("tool_use_id") != row["tool_use_id"]
    ):
        raise graph_contract.DispatchDeniedError(
            "dispatch_unauthorized", "native spawn does not match its consumed dispatch authorization"
        )


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
    ids: set[str] = set()
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
