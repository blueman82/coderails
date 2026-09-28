#!/usr/bin/env python3
"""Tolerant Claude transcript extraction for discipline and lifecycle hooks."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast


def records(path: str, tail_lines: int = 0) -> list[dict[str, Any]]:
    """Read JSON objects while ignoring individually malformed transcript lines."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    result: list[dict[str, Any]] = []
    for line in lines[-tail_lines:] if tail_lines else lines:
        try:
            value: object = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            result.append(cast(dict[str, Any], value))
    return result


def content(record: dict[str, Any]) -> object:
    """Return message content only from a structurally valid message object."""
    message: object = record.get("message")
    return cast(dict[str, Any], message).get("content") if isinstance(message, dict) else None


def tool_uses(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return object-shaped tool uses from a native assistant transcript entry."""
    value = content(record)
    if record.get("type") != "assistant" or not isinstance(value, list):
        return []
    return [
        cast(dict[str, Any], block)
        for block in cast(list[object], value)
        if isinstance(block, dict) and cast(dict[str, Any], block).get("type") == "tool_use"
    ]


def extract_last_text(transcript: str, tail_lines: int) -> str:
    """Return the final nonempty assistant text in the transcript's tail window."""
    entries = records(transcript, tail_lines)
    for record in entries:
        value = content(record)
        if record.get("type") == "assistant" and isinstance(value, list):
            for block in cast(list[object], value):
                if isinstance(block, dict):
                    item = cast(dict[str, Any], block)
                    if item.get("type") == "text" and isinstance(item.get("text"), (dict, list)):
                        return ""
    for record in reversed(entries):
        if record.get("type") != "assistant":
            continue
        value = content(record)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            text = " ".join(
                str(cast(dict[str, Any], block).get("text") or "")
                for block in cast(list[object], value)
                if isinstance(block, dict) and cast(dict[str, Any], block).get("type") == "text"
            )
            if text:
                return text
    return ""


def stable_text(transcript: str, tail_lines: int, max_attempts: int, sleep_s: float) -> tuple[str, int]:
    """Retry extraction until two consecutive nonempty text lengths agree."""
    previous, attempts, text = -1, 0, ""
    while attempts < max_attempts:
        text = extract_last_text(transcript, tail_lines)
        if len(text) == previous and text:
            break
        previous = len(text)
        attempts += 1
        if attempts < max_attempts:
            time.sleep(sleep_s)
    return text, attempts


def file_count(transcript: str) -> int:
    """Count distinct edited paths after the most recent genuine user prompt."""
    entries = records(transcript)
    cutoff = -1
    for index, record in enumerate(entries):
        value = content(record)
        genuine = isinstance(value, str) and bool(value)
        if isinstance(value, list):
            genuine = any(
                isinstance(block, dict) and cast(dict[str, Any], block).get("type") == "text"
                for block in cast(list[object], value)
            )
        if record.get("type") == "user" and genuine:
            cutoff = index
    paths: set[str] = set()
    for record in entries[cutoff + 1 :]:
        for tool in tool_uses(record):
            data: object = tool.get("input")
            if tool.get("name") in {"Write", "Edit", "MultiEdit"}:
                if data is not None and not isinstance(data, dict):
                    return 0
                paths.add(str(cast(dict[str, Any], data or {}).get("file_path")))
    return len(paths)


def mine_hook_blocks(session: str, log_file: str = "") -> dict[str, dict[str, int]]:
    """Aggregate session-authored discipline records into event and flag counts."""
    path = Path(log_file or os.environ.get("CLAUDE_DISCIPLINE_LOG", str(Path.home() / ".claude/discipline.log")))
    if not session:
        return {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return {}
    result: dict[str, dict[str, int]] = {}
    for line in lines:
        tokens = line.split()
        if f"session={session}" not in tokens:
            continue
        hook = next((token[5:] for token in reversed(tokens) if token.startswith("hook=")), "")
        if hook:
            counts = result.setdefault(hook, {"events": 0, "flagged": 0})
            counts["events"] += 1
            counts["flagged"] += int(any(token in {"blocked=1", "would_block=1", "nudged=1"} for token in tokens))
    return result


if __name__ == "__main__":
    print(json.dumps(mine_hook_blocks(sys.argv[1] if len(sys.argv) > 1 else "")))
