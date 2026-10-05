"""Count typed-state, attestation and eval-verdict reason codes from per-session trace rows (read-only).

Usage: python3 scripts/lib/state_counters.py [--since <ISO ts>]   (loop dir: CLAUDE_AGENTIC_LOOP_DIR or default)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

EVAL_STATUSES = (
    "GO",
    "VERIFICATION_LEVEL0",
    "FROZEN",
    "NO-GO",
    "ABSENT",
    "UNJUSTIFIED",
    "UNSTAMPED",
    "STALE",
    "TAMPERED",
)
REASONS = (
    "hook_state_unreadable",
    "nudge_first",
    "nudge_suppressed",
    "attest_missing",
    "attest_not_success",
    "attest_wrong_creator",
    "attest_not_bound",
    "predecessor_pending",
    "node_unknown",
    *(f"eval_verdict_{s.lower()}" for s in EVAL_STATUSES),
)


def count_reasons(root: Path, since: str = "") -> dict[str, int]:
    """Occurrences of each reason code across <root>/*/trace.jsonl, rows with ts >= since when given."""
    counts: dict[str, int] = dict.fromkeys(REASONS, 0)
    for trace in sorted(root.glob("*/trace.jsonl")):
        try:
            lines = trace.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            fields = cast("dict[str, Any]", row)
            code, stamp = fields.get("reason_code"), fields.get("ts")
            if since and not (isinstance(stamp, str) and stamp >= since):
                continue
            if isinstance(code, str) and code in counts:
                counts[code] += 1
    return counts


def main() -> int:
    """Print the counts as JSON."""
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv[:-1] else ""
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    print(json.dumps(count_reasons(root, since), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
