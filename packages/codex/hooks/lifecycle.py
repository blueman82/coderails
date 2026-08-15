#!/usr/bin/env python3
"""Lifecycle enforcement: JSON stdin, JSON stdout, non-zero on refusal."""

import json
import sys

REQUIRED_GATES = ("review", "eval", "proof", "integrity", "wiki", "teardown")


def validate(event: dict) -> tuple[bool, str]:
    if not isinstance(event, dict) or not isinstance(event.get("event"), str):
        return False, "event must contain a string event"
    state = event.get("state")
    if not isinstance(state, dict):
        return False, "state must be an object"
    if event["event"] == "complete":
        nodes = state.get("graph", {}).get("nodes", {})
        if state.get("status") != "complete" or not nodes:
            return False, "complete requires a successful state"
        if any(value.get("outcome") not in {"done", "skipped"} for value in nodes.values()):
            return False, "complete requires every node to succeed"
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
    try:
        allowed, reason = validate(json.load(sys.stdin))
    except (json.JSONDecodeError, OSError) as error:
        allowed, reason = False, f"invalid event: {error}"
    print(json.dumps({"allowed": allowed, "reason": reason}))
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
