"""Read native Claude dispatch and terminal records from the session transcript."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, cast

ENVELOPE_KEY = "CODERAILS_GRAPH_DISPATCH"


def object_value(value: object, label: str) -> dict[str, Any]:
    """Require an object at a native transcript boundary."""
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def records(path: Path) -> list[dict[str, Any]]:
    """Parse all nonblank native records, refusing partial or corrupt JSON."""
    try:
        return [
            object_value(json.loads(line), "transcript record")
            for line in path.read_text().splitlines()
            if line.strip()
        ]
    except (OSError, ValueError) as error:
        raise ValueError(f"malformed or unreadable transcript: {path}") from error


def transcript(session: str) -> Path:
    """Resolve exactly one session below the native projects directory."""
    if not session or "/" in session or session.startswith(".."):
        raise ValueError("invalid transcript session")
    default = (Path.home() / ".claude/projects").resolve()
    projects = Path(os.environ.get("CLAUDE_PROJECTS_DIR", str(default))).resolve()
    if projects != default and default not in projects.parents:
        raise ValueError("transcript location is outside native projects")
    matches = [
        path for path in projects.glob(f"*/{session}.jsonl") if path.is_file() and default in path.resolve().parents
    ]
    if len(matches) != 1:
        raise ValueError("session transcript must resolve uniquely")
    return matches[0]


def cursor(session: str) -> int:
    """Return the native record count captured before a wave dispatches."""
    return len(records(transcript(session)))


def envelope(prompt: object) -> dict[str, Any]:
    """Read a complete graph ownership envelope from the first prompt line."""
    if not isinstance(prompt, str) or not prompt.startswith(ENVELOPE_KEY + "="):
        raise ValueError("missing graph dispatch envelope")
    raw = prompt.split("\n", 1)[0].split("=", 1)[1]
    try:
        result = object_value(json.loads(raw), "dispatch envelope")
    except ValueError as error:
        raise ValueError("malformed graph dispatch envelope") from error
    if set(result) != {"session_id", "loop_id", "revision", "wave_id", "node_id"}:
        raise ValueError("invalid dispatch envelope fields")
    for key in ("session_id", "loop_id", "wave_id", "node_id"):
        if not isinstance(result[key], str) or not result[key].strip():
            raise ValueError(f"invalid dispatch envelope {key}")
    if type(result["revision"]) is not int or result["revision"] < 1:
        raise ValueError("invalid dispatch envelope revision")
    return result


def content(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Read native message content blocks without treating raw text as tools."""
    value = object_value(record.get("message", {}), "message").get("content", [])
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in cast(list[object], value) if isinstance(item, dict)]


def parent_records(path: Path, session: str) -> list[tuple[int, dict[str, Any]]]:
    """Retain main-thread native records with their original cursor offsets."""
    return [
        (line, record)
        for line, record in enumerate(records(path), 1)
        if record.get("isSidechain") is not True and record.get("sessionId", session) == session
    ]


def spawns(path: Path, session: str) -> list[dict[str, Any]]:
    """Derive native Agent requests, rejecting conflicting duplicate tool identities."""
    entries = parent_records(path, session)
    results: dict[str, dict[str, Any]] = {}
    for _, record in entries:
        if record.get("type") != "user":
            continue
        for block in content(record):
            if block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                key = block["tool_use_id"]
                raw = record.get("toolUseResult")
                if not isinstance(raw, dict) and block.get("is_error") is not True:
                    continue
                value = (
                    object_value(cast(object, raw), "native tool result")
                    if isinstance(raw, dict)
                    else {"is_error": True}
                )
                if key in results and results[key] != value:
                    raise ValueError("conflicting native tool results")
                results[key] = value
    found: dict[str, dict[str, Any]] = {}
    for line, record in entries:
        if record.get("type") != "assistant":
            continue
        for block in content(record):
            if block.get("type") != "tool_use" or block.get("name") != "Agent":
                continue
            request = object_value(block.get("input"), "Agent input")
            prompt = request.get("prompt", "")
            if not isinstance(prompt, str) or not prompt.startswith(ENVELOPE_KEY + "="):
                continue
            ownership = envelope(prompt)
            key, role = block.get("id"), request.get("subagent_type")
            if not isinstance(key, str) or not key or not isinstance(role, str) or not role.strip():
                raise ValueError("native Agent dispatch lacks tool identity or provider role")
            identifier = record.get("uuid")
            if not isinstance(identifier, str) or not identifier.strip():
                raise ValueError("native Agent dispatch lacks its raw record UUID")
            row = {
                **ownership,
                "line": line,
                "tool_use_id": key,
                "record_uuid": identifier,
                "subagent_type": role,
                "prompt": prompt,
                "native_result": results.get(key, {}),
            }
            if key in found:
                if {k: v for k, v in row.items() if k != "line"} != {
                    k: v for k, v in found[key].items() if k != "line"
                }:
                    raise ValueError("conflicting duplicate native Agent spawn")
            else:
                found[key] = row
    return list(found.values())


def notifications(path: Path, session: str) -> dict[str, list[dict[str, str]]]:
    """Read only harness-origin notifications, never echoed tool or user text."""
    found: dict[str, list[dict[str, str]]] = {}
    for _, record in parent_records(path, session):
        value: object = None
        if record.get("type") == "queue-operation":
            value = record.get("content")
        elif record.get("type") == "user" and record.get("origin", {}).get("kind") == "task-notification":
            value = record.get("message", {}).get("content")
        if not isinstance(value, str):
            continue
        for block in re.findall(r"<task-notification>(.*?)</task-notification>", value, re.S):
            fields: dict[str, str] = {}
            for tag in ("tool-use-id", "task-id", "status", "result"):
                match = re.search(rf"<{tag}>(.*?)</{tag}>", block, re.S)
                fields[tag] = match[1] if match else ""
            key = fields["tool-use-id"]
            if key and fields not in found.setdefault(key, []):
                found[key].append(fields)
    return found


def child_identity(
    path: Path, session: str, spawn: dict[str, Any], completed: bool, failed_launch: bool = False
) -> str:
    """Check native child ownership and the actual requested provider role."""
    result = spawn["native_result"]
    if result.get("status") == "teammate_spawned":
        raise ValueError("mailbox/teammate dispatch cannot prove native graph completion")
    agent = result.get("agentId")
    if not isinstance(agent, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", agent):
        if failed_launch and result.get("is_error") is True:
            return ""
        raise ValueError("native dispatch has no child identity")
    child = path.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"
    entries = records(child)
    if not entries or any(
        item.get("agentId") != agent or item.get("sessionId") != session or item.get("isSidechain") is not True
        for item in entries
    ):
        raise ValueError("native child belongs to another parent session or identity")
    first = entries[0].get("message", {})
    if first.get("role") != "user" or first.get("content") != spawn["prompt"]:
        raise ValueError("native child prompt does not match parent dispatch")
    roles = {item["attributionAgent"] for item in entries if item.get("attributionAgent") is not None}
    if roles and roles != {spawn["subagent_type"]}:
        raise ValueError("native child provider role does not match requested subagent_type")
    if completed and roles != {spawn["subagent_type"]}:
        raise ValueError("completed native child has no matching provider role")
    if completed:
        validate_child_terminal(entries)
    return agent


def validate_child_terminal(entries: list[dict[str, Any]]) -> None:
    """Require a real final assistant message rather than attribution alone."""
    assistants = [item for item in entries if item.get("type") == "assistant"]
    if not assistants:
        raise ValueError("native child has no terminal assistant message")
    last = assistants[-1]
    message = object_value(last.get("message"), "native child terminal message")
    blocks = content(last)
    text = any(
        block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip() for block in blocks
    )
    if (
        message.get("role") != "assistant"
        or message.get("stop_reason") not in {"end_turn", "stop_sequence"}
        or not text
        or any(block.get("type") == "tool_use" for block in blocks)
        or last.get("isApiErrorMessage")
        or last.get("is_api_error_message")
        or last.get("error")
    ):
        raise ValueError("native child has no successful terminal assistant message")
