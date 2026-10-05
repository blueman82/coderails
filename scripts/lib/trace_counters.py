"""Read-only counters over append-only trace rows, deduped by event_id. Counts only; row inputs are never kept."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

CONTEXT_COMMANDS = ("context_manifest", "context_route")


def count_events(
    files: list[Path], key_of: Callable[[dict[str, Any]], str], keep: Callable[[dict[str, Any]], bool] = bool
) -> dict[str, Any]:
    """Count rows once per event_id across files; torn, keyless or non-object lines are malformed."""
    seen: set[str] = set()
    by_reason: dict[str, int] = {}
    duplicates = malformed = 0
    for file in dict.fromkeys(files):
        try:
            lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
                event_id = str(row["event_id"])
                if not keep(row):
                    continue
                key = key_of(row)
            except (ValueError, KeyError, TypeError):
                malformed += 1
                continue
            if event_id in seen:
                duplicates += 1
                continue
            seen.add(event_id)
            by_reason[key] = by_reason.get(key, 0) + 1
    return {"events": len(seen), "duplicates": duplicates, "malformed": malformed, "by_reason": by_reason}


def eval_trace_counts(files: list[Path]) -> dict[str, Any]:
    """Count eval_trace.jsonl rows by command|outcome|reason_code."""
    return count_events(files, lambda row: "|".join(str(row[k]) for k in ("command", "outcome", "reason_code")))


def context_counts(files: list[Path]) -> dict[str, Any]:
    """Count context manifest and route rows from trace.jsonl files by command/reason_code."""
    return count_events(
        files,
        lambda row: f"{row['command']}/{row['reason_code']}",
        lambda row: row.get("command") in CONTEXT_COMMANDS,
    )
