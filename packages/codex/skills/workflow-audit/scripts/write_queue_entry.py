#!/usr/bin/env python3
"""Write one privacy-bounded dashboard queue entry for a propose verdict."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import cast


def _parse_args() -> argparse.Namespace:
    """Parse the stable queue-writer command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-dir", type=Path, default=Path.home() / ".codex/coderails-dashboard/approvals")
    parser.add_argument("--count", default="")
    parser.add_argument("--sessions", default="")
    return parser.parse_args()


def _positive_int(value: str) -> int:
    """Apply the shell contract's numeric fallback."""
    return int(value) if value.isdigit() else 0


def _default(value: object | None, fallback: object) -> object:
    """Apply jq's null-only default operator without coercing false or zero."""
    return fallback if value is None else value


def _main() -> int:
    """Write one protected queue entry for a valid propose verdict."""
    args = _parse_args()
    try:
        sessions_value = json.loads(args.sessions)
    except json.JSONDecodeError:
        sessions_value = []
    sessions = cast(list[object], sessions_value) if isinstance(sessions_value, list) else []
    try:
        verdict_value = json.load(sys.stdin)
    except json.JSONDecodeError:
        verdict_value = None
    if not isinstance(verdict_value, dict):
        print("jq_parse_error:stdin", file=sys.stderr)
        return 1
    verdict = cast(dict[str, object], verdict_value)
    if verdict.get("verdict") != "propose":
        return 0
    tool_input = {
        "cluster_ngram": _default(verdict.get("cluster_ngram"), []),
        "count": _positive_int(args.count),
        "sessions": sessions,
        "task_summary": _default(verdict.get("task_summary"), ""),
        "proposed_name": _default(verdict.get("proposed_name"), ""),
        "proposed_description": _default(verdict.get("proposed_description"), ""),
    }
    canonical = json.dumps(tool_input, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    args.queue_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(args.queue_dir, 0o700)
    entry = {
        "hash": digest,
        "toolName": "workflow-audit:propose-skill",
        "toolInput": tool_input,
        "createdAt": int(time.time() * 1000),
        "status": "pending",
    }
    destination = args.queue_dir / f"{digest}.json"
    destination.write_text(json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(destination, 0o600)
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
