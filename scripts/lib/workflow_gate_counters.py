"""Tally publication-gate trace rows from measure_graph_alignment.py's `trace.by_reason` map.

Usage: python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py
Keys in the input are `command/outcome/reason_code`; output is {command: {outcome/reason_code: count}} for the
commands in COMMANDS. Later units add their own command names here, so no other file needs editing.
"""

from __future__ import annotations

import json
import sys

COMMANDS = ("diff-manifest", "review-passes", "eval-level", "publication", "argv")


def counts(by_reason: dict[str, int]) -> dict[str, dict[str, int]]:
    """Return {command: {outcome/reason_code: count}} for the gate commands only."""
    tally: dict[str, dict[str, int]] = {name: {} for name in COMMANDS}
    for key, value in sorted(by_reason.items()):
        command, _, rest = key.partition("/")
        if command in tally:
            tally[command][rest] = value
    return tally


if __name__ == "__main__":
    print(json.dumps(counts(json.load(sys.stdin).get("trace", {}).get("by_reason", {})), indent=2))
