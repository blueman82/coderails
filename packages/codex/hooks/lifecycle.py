#!/usr/bin/env python3
"""Lifecycle enforcement: JSON stdin, JSON stdout, non-zero on refusal."""

import json
import sys


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
        if not isinstance(state.get("teardown"), dict):
            return False, "complete requires teardown metadata"
    return True, "allowed"


try:
    allowed, reason = validate(json.load(sys.stdin))
except (json.JSONDecodeError, OSError) as error:
    allowed, reason = False, f"invalid event: {error}"
print(json.dumps({"allowed": allowed, "reason": reason}))
raise SystemExit(0 if allowed else 1)
