"""Count typed worker results and recorded decisions from per-loop trace rows and state (read-only, counts only).

Usage: python3 scripts/lib/worker_counters.py [--since <ISO ts>]   (loop dir: CLAUDE_AGENTIC_LOOP_DIR or default)
Trace rows come from `record-wave` and `record-decision` in each loop's recovery-trace.jsonl on both providers:
`worker_status_<reason>` and `final_report_invalid` are whole-report refusals, `worker_status_<status>` a recorded typed
status, `final_report_recorded` a stored report, `decision_recorded` a ledger row. `pending_statuses` is read from each
progress.json (worker_statuses rows still `decision_pending`): a number that stays above zero means a human question was
never answered or never marked resolved with `record-decision --worker-status-seq`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
from worker_status import REASONS, STATUSES

REASON_CODES = (
    *(f"worker_status_{reason}" for reason in REASONS[1:]),
    "final_report_invalid",
    *(f"worker_status_{status.lower()}" for status in STATUSES),
    "final_report_recorded",
    "decision_recorded",
)


def count_reasons(root: Path, since: str = "") -> dict[str, int]:
    """Occurrences of each reason code, once per (file, event_id), rows with ts >= since when given; plus pending."""
    counts: dict[str, int] = {**dict.fromkeys(REASON_CODES, 0), "pending_statuses": 0}
    for trace in sorted([*root.glob("*/recovery-trace.jsonl"), *root.glob("*/*/recovery-trace.jsonl")]):
        try:
            lines = trace.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError):
            continue
        seen: set[str] = set()
        for text in lines:
            try:
                row: object = json.loads(text)
            except ValueError:
                continue
            fields = cast("dict[str, Any]", row) if isinstance(row, dict) else {}
            code, stamp, event = fields.get("reason_code"), fields.get("ts"), fields.get("event_id")
            if since and not (isinstance(stamp, str) and stamp >= since):
                continue
            if isinstance(code, str) and code in counts and not (isinstance(event, str) and event in seen):
                counts[code] += 1
                if isinstance(event, str):
                    seen.add(event)
    for state in [*root.glob("*/progress.json"), *root.glob("*/*/progress.json")]:
        try:
            data: object = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows: object = cast("dict[str, object]", data).get("worker_statuses") if isinstance(data, dict) else None
        for row in cast("list[object]", rows) if isinstance(rows, list) else []:
            if isinstance(row, dict) and cast("dict[str, object]", row).get("decision_pending") is True:
                counts["pending_statuses"] += 1
    return counts


def counts(loop_roots: list[Path]) -> dict[str, int]:
    """The measurement entry point: the sum of count_reasons over each loop root."""
    total: dict[str, int] = {}
    for root in loop_roots:
        for name, value in count_reasons(root).items():
            total[name] = total.get(name, 0) + value
    return total


def main() -> int:
    """Print the counts as JSON."""
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv[:-1] else ""
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    print(json.dumps(count_reasons(root, since), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
