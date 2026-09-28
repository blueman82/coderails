#!/usr/bin/env python3
"""Write one owner-only pending queue entry for a whitelisted propose verdict."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "dashboard/scripts"))
from audit_common import AuditParser, number
from canonical_json import JsonValue, dumps, loads


def fallback(value: JsonValue, default: JsonValue) -> JsonValue:
    """Preserve jq alternative semantics: only null and false select the default."""
    return default if value is None or value is False else value


def write_entry(queue: Path, tool_input: dict[str, JsonValue]) -> str:
    """Hash exact canonical input bytes and publish a complete private queue file."""
    digest = hashlib.sha256(dumps(tool_input).encode("utf-8")).hexdigest()
    entry: dict[str, JsonValue] = {
        "hash": digest,
        "toolName": "workflow-audit:propose-skill",
        "toolInput": tool_input,
        "createdAt": time.time_ns() // 1000000,
        "status": "pending",
    }
    queue.mkdir(parents=True, exist_ok=True, mode=0o700)
    queue.chmod(0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=queue, delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(dumps(entry) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, queue / f"{digest}.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return digest


def main() -> int:
    """Read a verdict object, keep only six fields, and silently ignore non-proposals."""
    parser = AuditParser(description=__doc__)
    parser.add_argument("--queue-dir", default=str(Path.home() / ".claude/coderails-dashboard/approvals"))
    parser.add_argument("--count", default="")
    parser.add_argument("--sessions", default="")
    args = parser.parse_args()
    try:
        verdict = loads(sys.stdin.read())
        if not isinstance(verdict, dict):
            raise ValueError("not an object")
    except ValueError:
        print("jq_parse_error:stdin", file=sys.stderr)
        return 1
    if verdict.get("verdict") != "propose":
        return 0
    try:
        sessions = loads(args.sessions)
    except ValueError:
        sessions = []
    tool_input: dict[str, JsonValue] = {
        "cluster_ngram": fallback(verdict.get("cluster_ngram"), []),
        "count": number(args.count, 0),
        "sessions": sessions if isinstance(sessions, list) else [],
        "task_summary": fallback(verdict.get("task_summary"), ""),
        "proposed_name": fallback(verdict.get("proposed_name"), ""),
        "proposed_description": fallback(verdict.get("proposed_description"), ""),
    }
    try:
        print(write_entry(Path(args.queue_dir), tool_input))
    except (OSError, ValueError) as error:
        print(f"queue_write_error:{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
