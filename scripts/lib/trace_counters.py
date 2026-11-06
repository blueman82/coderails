"""Read-only counters over append-only trace rows, deduped by event_id. Counts only; row inputs are never kept."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

CONTEXT_COMMANDS = ("context_manifest", "context_route")


def measured_reasons(payload: object, reasons: tuple[str, ...]) -> dict[str, int]:
    """Read typed reason totals from measure_graph_alignment's trace.by_reason."""
    if not isinstance(payload, dict):
        raise ValueError("missing trace summary")
    trace = cast("dict[str, object]", payload).get("trace")
    if not isinstance(trace, dict):
        raise ValueError("missing trace summary")
    by_reason = cast("dict[str, object]", trace).get("by_reason")
    if not isinstance(by_reason, dict):
        raise ValueError("missing trace.by_reason")
    counts: dict[str, int] = dict.fromkeys(reasons, 0)
    for key, value in cast("dict[object, object]", by_reason).items():
        if not isinstance(key, str) or type(value) is not int or value < 0:
            raise ValueError("invalid trace.by_reason entry")
        code = key.rpartition("/")[2]
        if code in counts:
            counts[code] += value
    return counts


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
