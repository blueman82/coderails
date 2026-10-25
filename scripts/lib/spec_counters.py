"""Count graph-spec enforcement, `instantiate` and plan skip rows from per-session trace rows (read-only, counts only).

Usage: python3 scripts/lib/spec_counters.py [--since <ISO ts>]   (loop dir: CLAUDE_AGENTIC_LOOP_DIR or default)
`spec_*` codes are loads/transitions refused because the graph drifted from graph-spec.yaml; `instantiate_*` come from
`graph.py instantiate`; `skip_when_met` is one count per `plan` call in which a node's machine skip predicate held
(a plan over N such nodes is one event). All rows live in each loop's recovery-trace.jsonl.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

REASONS = (
    "spec_edge_missing",
    "spec_unknown_node",
    "spec_node_missing",
    "spec_hash_mismatch",
    "spec_join_inputs",
    "spec_profile_downgrade",
    "instantiate_ok",
    "instantiate_noop",
    "instantiate_refused_foreign",
    "instantiate_refused_state",
    "instantiate_refused_nonempty",
    "instantiate_refused_bad_id",
    "skip_when_met",
)


def count_reasons(root: Path, since: str = "") -> dict[str, int]:
    """Occurrences of each reason code, once per (file, event_id), rows with ts >= since when given."""
    counts: dict[str, int] = dict.fromkeys(REASONS, 0)
    for trace in sorted([*root.glob("*/trace.jsonl"), *root.glob("*/*/recovery-trace.jsonl")]):
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
