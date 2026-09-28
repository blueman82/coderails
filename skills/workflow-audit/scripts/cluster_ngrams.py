#!/usr/bin/env python3
"""Cluster whitelisted tool-use windows across distinct transcript sessions."""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Any, cast

from audit_common import AuditParser, array_value, emit, number, object_value, text_value


def read_sessions() -> list[dict[str, Any]]:
    """Isolate malformed and non-object input lines using documented diagnostics."""
    sessions: list[dict[str, Any]] = []
    for index, line in enumerate(sys.stdin, 1):
        if not line.strip():
            continue
        try:
            value: object = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("not an object")
            sessions.append(object_value(cast(object, value)))
        except ValueError:
            print(f"jq_parse_error:{index}", file=sys.stderr)
    return sessions


def event_text(value: object) -> str:
    """Construct only documented tool/head strings without coercing private fields."""
    event = object_value(value)
    tool = text_value(event.get("tool"))
    head = event.get("head")
    return f"{tool}:{head}" if tool and isinstance(head, str) else tool


def cluster(sessions: list[dict[str, Any]], minimum: int, top: int) -> dict[str, Any]:
    """Count every window while thresholding by deduplicated session identifiers."""
    groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for session in sessions:
        sequence = [event_text(event) for event in array_value(session.get("events"))]
        identifier = text_value(session.get("session_id"))
        for size in range(2, 6):
            for start in range(len(sequence) - size + 1):
                groups[tuple(sequence[start : start + size])].append(identifier)
    clusters: list[dict[str, Any]] = []
    below = 0
    for gram in sorted(groups, key=lambda value: (len(value), value)):
        occurrences = groups[gram]
        support = sorted(set(occurrences))
        if len(support) < minimum:
            below += 1
        else:
            clusters.append({"ngram": list(gram), "n": len(gram), "count": len(occurrences), "sessions": support})
    clusters.sort(key=lambda value: (-value["count"], -value["n"]))
    return {
        "scanned_sessions": len(sessions),
        "clusters": clusters[:top],
        "diagnostics": {"below_threshold": below, "truncated": len(clusters) > top},
    }


def main() -> int:
    """Parse bounds and emit one aggregate object, including clean empty results."""
    parser = AuditParser(description=__doc__)
    parser.add_argument("--min-sessions", default="3")
    parser.add_argument("--top", default="50")
    args = parser.parse_args()
    emit(cluster(read_sessions(), number(args.min_sessions, 3), max(1, number(args.top, 50))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
