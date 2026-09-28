#!/usr/bin/env python3
"""Scan assistant tool events under WORKFLOW_AUDIT_ROOT, preserving whitelisted heads only."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from audit_common import AuditParser, array_value, emit, number, object_value, text_value


def records(path: Path) -> list[dict[str, Any]]:
    """Isolate corrupt transcript lines while retaining valid object records."""
    result: list[dict[str, Any]] = []
    corrupt = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        print(f"jq_parse_error:{path}", file=sys.stderr)
        return result
    for line in lines:
        if not line.strip():
            continue
        try:
            value: object = json.loads(line)
        except ValueError:
            corrupt = True
            continue
        if isinstance(value, dict):
            result.append(object_value(cast(object, value)))
        elif value is None or value is False:
            corrupt = True
    if corrupt:
        print(f"jq_parse_error:{path}", file=sys.stderr)
    return result


def latest(values: list[dict[str, Any]]) -> str:
    """Select assistant/user message timestamps, excluding bookkeeping recency."""
    return max(
        (text_value(value.get("timestamp")) for value in values if value.get("type") in ("assistant", "user")),
        default="",
    )


def recent(timestamp: str, cutoff: float) -> bool:
    """Retain unknown timestamps while excluding known activity before the cutoff."""
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() >= cutoff
    except (ValueError, OverflowError):
        return True


def events(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract only tool name and the explicit Bash/Skill/Agent input whitelist."""
    result: list[dict[str, Any]] = []
    fields = {"Bash": "command", "Skill": "skill", "Agent": "subagent_type"}
    for record in values:
        if record.get("type") != "assistant":
            continue
        for value in array_value(object_value(record.get("message")).get("content")):
            item = object_value(value)
            if item.get("type") != "tool_use":
                continue
            name = text_value(item.get("name"))
            event: dict[str, Any] = {"tool": name}
            if name in fields:
                head = text_value(object_value(item.get("input")).get(fields[name]))
                event["head"] = " ".join(head.split()[:2]) if name == "Bash" else head
            result.append(event)
    return result


def main() -> int:
    """Resolve project/session scope and emit one privacy-whitelisted record per session."""
    parser = AuditParser(description=__doc__)
    parser.add_argument("--all-projects", dest="project", action="store_const", const=None)
    parser.add_argument("--project")
    parser.add_argument("--days", default="14")
    parser.add_argument("--last-sessions", default="0")
    args = parser.parse_args()
    root = Path(os.environ.get("WORKFLOW_AUDIT_ROOT", str(Path.home() / ".claude/projects")))
    projects = [root / args.project] if args.project else sorted(root.iterdir()) if root.is_dir() else []
    files = [
        path for project in projects if project.is_dir() for path in sorted(project.glob("*.jsonl")) if path.is_file()
    ]
    size = sum(path.stat().st_size for path in files)
    print(f"scanning file_count={len(files)} total_mb={size / 1048576:.2f}", file=sys.stderr)
    count = number(args.last_sessions, 0)
    cutoff = time.time() - number(args.days, 14) * 86400
    loaded: dict[Path, list[dict[str, Any]]] = {}
    for path in files:
        if path.stem == os.environ.get("CLAUDE_CODE_SESSION_ID", ""):
            print(f"skipped_own_session:{path}", file=sys.stderr)
        else:
            loaded[path] = records(path)
    selected: list[Path] = []
    if count:
        for project in projects:
            candidates = [path for path in loaded if path.parent == project]
            selected.extend(sorted(candidates, key=lambda path: latest(loaded[path]), reverse=True)[:count])
    else:
        selected = [path for path, values in loaded.items() if recent(latest(values), cutoff)]
    for path in selected:
        sequence = events(loaded[path])
        emit(
            {
                "session_id": path.stem,
                "project_slug": path.parent.name,
                "event_count": len(sequence),
                "events": sequence,
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
