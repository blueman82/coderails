"""Tally diff-manifest trace rows from measure_graph_alignment.py's `trace.by_reason` map.

Usage: python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/manifest_counters.py
Keys in the input are `command/outcome/reason_code`; output keys are `outcome/reason_code` for diff-manifest only.
"""

from __future__ import annotations

import json
import sys

PREFIX = "diff-manifest/"


def counts(by_reason: dict[str, int]) -> dict[str, int]:
    """Return diff-manifest tallies keyed `outcome/reason_code`."""
    return {k[len(PREFIX) :]: v for k, v in sorted(by_reason.items()) if k.startswith(PREFIX)}


if __name__ == "__main__":
    print(json.dumps(counts(json.load(sys.stdin).get("trace", {}).get("by_reason", {})), indent=2))
