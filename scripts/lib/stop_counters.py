"""Count stop-row blocks and progress.json conversions from per-session trace rows (read-only, counts only).

Usage: python3 scripts/lib/stop_counters.py [--since <ISO ts>]   (loop dir: CLAUDE_AGENTIC_LOOP_DIR or default)
`stop_row_missing` is a Stop blocked because no recorded stop row existed (either provider); `stale_stop_row` is a row
from an earlier turn that never released. Convert rows live in each loop's recovery-trace.jsonl.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/graph-semantics"))
from graph_convert import CODES as CONVERT_REFUSALS

BLOCK_CODES = ("stop_row_missing", "stale_stop_row")
CONVERT_CODES = ("convert_ok", *(f"convert_refused_{code}" for code in CONVERT_REFUSALS))
REASONS = (*BLOCK_CODES, *CONVERT_CODES)


def count_reasons(root: Path, since: str = "") -> dict[str, int]:
    """Occurrences of each reason code, once per (file, event_id), rows with ts >= since when given."""
    counts: dict[str, int] = dict.fromkeys(REASONS, 0)
    files = [*root.glob("*/trace.jsonl"), *root.glob("*/*/recovery-trace.jsonl")]
    for trace in sorted(files):
        try:
            lines = trace.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            continue
        seen: set[str] = set()
        for text in lines:
            try:
                row = json.loads(text)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            fields = cast("dict[str, Any]", row)
            code, stamp, event = fields.get("reason_code"), fields.get("ts"), fields.get("event_id")
            if since and not (isinstance(stamp, str) and stamp >= since):
                continue
            if isinstance(code, str) and code in counts and not (isinstance(event, str) and event in seen):
                counts[code] += 1
                if isinstance(event, str):
                    seen.add(event)
    return counts


def main() -> int:
    """Print the counts as JSON."""
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv[:-1] else ""
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    print(json.dumps(count_reasons(root, since), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
