#!/usr/bin/env python3
"""Cluster repeated privacy-bounded tool-event n-grams from JSONL stdin."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import TypedDict, cast


class _Cluster(TypedDict):
    ngram: list[str]
    n: int
    count: int
    sessions: list[str]


def _compact(value: object) -> str:
    """Serialize an output value in the established compact JSON form."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _positive_int(value: str, default: int) -> int:
    """Apply the shell contract's numeric fallback."""
    return int(value) if value.isdigit() else default


def _parse_args() -> argparse.Namespace:
    """Parse the stable clustering command-line contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-sessions", default="3")
    parser.add_argument("--top", default="50")
    return parser.parse_args()


def _event_text(event: object) -> str:
    """Render an event using only its whitelisted tool and head fields."""
    if not isinstance(event, dict):
        return ""
    fields = cast(dict[str, object], event)
    tool_value = fields.get("tool")
    head_value = fields.get("head")
    tool = tool_value if isinstance(tool_value, str) else ""
    head = head_value if isinstance(head_value, str) else None
    return f"{tool}:{head}" if tool and head else tool


def _main() -> int:
    """Read JSONL, cluster recurring n-grams, and emit one result object."""
    args = _parse_args()
    minimum = _positive_int(args.min_sessions, 3)
    top = max(_positive_int(args.top, 50), 1)
    sessions: list[dict[str, object]] = []
    for line_number, line in enumerate(sys.stdin, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            value = None
        if not isinstance(value, dict):
            print(f"jq_parse_error:{line_number}", file=sys.stderr)
            continue
        sessions.append(cast(dict[str, object], value))
    occurrences: dict[tuple[int, tuple[str, ...]], list[str]] = defaultdict(list)
    for session in sessions:
        events = session.get("events")
        event_values = cast(list[object], events) if isinstance(events, list) else []
        values = [_event_text(event) for event in event_values]
        raw_session_id = session.get("session_id")
        session_id = raw_session_id if isinstance(raw_session_id, str) else ""
        for size in range(2, min(5, len(values)) + 1):
            for start in range(len(values) - size + 1):
                occurrences[(size, tuple(values[start : start + size]))].append(session_id)
    all_clusters: list[_Cluster] = [
        {"ngram": list(ngram), "n": size, "count": len(ids), "sessions": sorted(set(ids))}
        for (size, ngram), ids in occurrences.items()
        if len(set(ids)) >= minimum
    ]
    all_clusters.sort(key=lambda cluster: (-cluster["count"], -cluster["n"]))
    below_threshold = sum(1 for ids in occurrences.values() if len(set(ids)) < minimum)
    print(
        _compact(
            {
                "scanned_sessions": len(sessions),
                "clusters": all_clusters[:top],
                "diagnostics": {"below_threshold": below_threshold, "truncated": len(all_clusters) > top},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
