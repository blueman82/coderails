#!/usr/bin/env python3
"""Generic lifecycle enforcement: JSON in, JSON out, no provider assumptions."""

from __future__ import annotations

import json
import sys


def validate(event: dict) -> tuple[bool, str]:
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        return False, "event must be an object with a string event"
    state = event.get("state", {})
    if not isinstance(state, dict):
        return False, "state must be an object"
    graph = state.get("graph", {})
    nodes = graph.get("nodes", {}) if isinstance(graph, dict) else {}
    if event["event"] == "complete":
        if state.get("status") != "complete":
            return False, "complete requires state.status=complete"
        if not isinstance(nodes, dict) or any(
            not isinstance(node, dict) or node.get("outcome") not in {"done", "skipped"}
            for node in nodes.values()
        ):
            return False, "complete requires every graph node to be terminal-success"
        if not isinstance(state.get("retro"), dict):
            return False, "complete requires retro object"
    return True, "allowed"


def main() -> int:
    event = json.load(sys.stdin)
    allowed, reason = validate(event)
    print(json.dumps({"allowed": allowed, "reason": reason}))
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
