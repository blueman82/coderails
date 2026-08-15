#!/usr/bin/env python3
"""Generic lifecycle enforcement: JSON in, JSON out, no provider assumptions."""

from __future__ import annotations

import json
import sys

REQUIRED_GATES = ("review", "eval", "proof", "integrity", "wiki", "teardown")


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
        if state.get("mode") == "fixture" or state.get("status") == "fixture":
            return False, "fixture state cannot be complete"
        gates = state.get("gates")
        if not isinstance(gates, dict):
            return False, "complete requires gate evidence"
        for gate in REQUIRED_GATES:
            evidence = gates.get(gate)
            if not isinstance(evidence, dict) or evidence.get("outcome") not in {"done", "skipped"} or not evidence.get("evidence"):
                return False, f"complete requires evidence for gate {gate}"
        teardown = state.get("teardown")
        if not isinstance(teardown, dict) or teardown.get("provider") != "codex" or not teardown.get("evidence"):
            return False, "complete requires Codex teardown evidence"
        retro = state.get("retro")
        if not isinstance(retro, dict) or retro.get("provider") != "codex" or retro.get("status") != "complete":
            return False, "complete requires valid Codex retro"
    return True, "allowed"


def main() -> int:
    event = json.load(sys.stdin)
    allowed, reason = validate(event)
    print(json.dumps({"allowed": allowed, "reason": reason}))
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
