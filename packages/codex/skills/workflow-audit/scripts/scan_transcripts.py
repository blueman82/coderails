#!/usr/bin/env python3
"""Scan native Codex session JSONL into privacy-bounded tool events."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast


def _compact(value: object) -> str:
    """Serialize an output value in the established compact JSON form."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _parse_records(path: Path) -> list[dict[str, object]]:
    """Read valid JSON object lines and report any corrupt source line."""
    records: list[dict[str, object]] = []
    corrupt = False
    with path.open(encoding="utf-8") as source:
        for line in source:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                corrupt = True
                continue
            if isinstance(value, dict):
                records.append(cast(dict[str, object], value))
    if corrupt:
        print(f"jq_parse_error:{path}", file=sys.stderr)
    return records


def _text(value: object) -> str:
    """Return a string field or the empty value used by the old jq filters."""
    return value if isinstance(value, str) else ""


def _latest_timestamp(records: Iterable[dict[str, object]]) -> str:
    """Return the latest lexical ISO timestamp from a session transcript."""
    return max((_text(record.get("timestamp")) for record in records), default="")


def _timestamp_epoch(timestamp: str) -> float | None:
    """Convert an ISO timestamp to epoch seconds when it is parseable."""
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _session_events(records: Iterable[dict[str, object]]) -> list[dict[str, str]]:
    """Extract the four privacy-whitelisted completed native tool event types."""
    events: list[dict[str, str]] = []
    for record in records:
        payload = record.get("payload")
        if record.get("type") != "event_msg" or not isinstance(payload, dict):
            continue
        payload = cast(dict[str, object], payload)
        item = payload.get("item")
        if payload.get("type") != "item_completed" or not isinstance(item, dict):
            continue
        item = cast(dict[str, object], item)
        item_type = item.get("type")
        event: dict[str, str] | None = None
        if item_type == "CommandExecution":
            command = item.get("command")
            head = ""
            command_values = cast(list[object], command) if isinstance(command, list) else []
            if len(command_values) > 2:
                head = " ".join(_text(command_values[2]).split()[:2])
            event = {"tool": "CommandExecution"}
            if head:
                event["head"] = head
        elif item_type == "FileChange":
            event = {"tool": "FileChange"}
        elif item_type == "Extension":
            kind = _text(item.get("kind"))
            event = {"tool": "Extension"}
            if kind == "web.search":
                event["head"] = kind
        elif item_type == "CollabAgentToolCall":
            tool = _text(item.get("tool"))
            event = {"tool": "CollabAgentToolCall"}
            if tool in {"spawn_agent", "send_input", "wait", "close_agent"}:
                event["head"] = tool
        if event is not None:
            events.append(event)
    return events


def _metadata(records: Iterable[dict[str, object]]) -> dict[str, object] | None:
    """Return the first session metadata payload, if present."""
    for record in records:
        if record.get("type") == "session_meta" and isinstance(record.get("payload"), dict):
            return cast(dict[str, object], record["payload"])
    return None


def _parse_args() -> argparse.Namespace:
    """Parse the stable transcript-selection command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all-projects", action="store_true")
    scope.add_argument("--project")
    parser.add_argument("--days", default="14")
    parser.add_argument("--last-sessions", default="0")
    return parser.parse_args()


def _positive_int(value: str, default: int) -> int:
    """Apply the shell contract's numeric fallback."""
    return int(value) if value.isdigit() else default


def _main() -> int:
    """Emit one bounded JSON event sequence for each selected root session."""
    args = _parse_args()
    days = _positive_int(args.days, 14)
    last_sessions = _positive_int(args.last_sessions, 0)
    root = Path(os.environ.get("WORKFLOW_AUDIT_ROOT", Path.home() / ".codex/sessions"))
    own_session = os.environ.get("CODEX_SESSION_ID", "")
    own_thread = os.environ.get("CODEX_THREAD_ID", "")
    candidates: list[tuple[Path, str, str, str, list[dict[str, object]]]] = []
    files = sorted(root.rglob("*.jsonl")) if root.is_dir() else []
    for path in files:
        records = _parse_records(path)
        session = _metadata(records)
        if session is None:
            print(f"missing_session_meta:{path}", file=sys.stderr)
            continue
        if _text(session.get("parent_thread_id")):
            continue
        cwd = _text(session.get("cwd")).rstrip("/")
        slug = Path(cwd).name or "unknown"
        session_id = _text(session.get("session_id")) or _text(session.get("id"))
        thread_id = _text(session.get("id"))
        if not session_id:
            print(f"missing_session_id:{path}", file=sys.stderr)
            continue
        if (own_session and session_id in {own_session, thread_id}) or (own_thread and thread_id == own_thread):
            print(f"skipped_own_session:{path}", file=sys.stderr)
            continue
        if args.project and slug != args.project:
            continue
        candidates.append((path, slug, session_id, _latest_timestamp(records), records))
    total_bytes = sum(path.stat().st_size for path, *_ in candidates)
    print(f"scanning file_count={len(candidates)} total_mb={total_bytes / 1048576:.2f}", file=sys.stderr)
    if last_sessions:
        selected: list[tuple[Path, str, str, str, list[dict[str, object]]]] = []
        for slug in sorted({candidate[1] for candidate in candidates}):
            matching = sorted(
                (item for item in candidates if item[1] == slug),
                key=lambda item: item[3],
                reverse=True,
            )
            selected.extend(matching[:last_sessions])
    else:
        cutoff = datetime.now(timezone.utc).timestamp() - timedelta(days=days).total_seconds()
        selected = [item for item in candidates if (epoch := _timestamp_epoch(item[3])) is None or epoch >= cutoff]
    for _, slug, session_id, _, records in selected:
        events = _session_events(records)
        print(_compact({"session_id": session_id, "project_slug": slug, "event_count": len(events), "events": events}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
