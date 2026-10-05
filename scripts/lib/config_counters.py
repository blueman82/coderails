"""Count typed-config and wiki-schema reason codes from per-session trace rows (read-only)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

REASONS = (
    "config_unknown_key",
    "config_bad_type",
    "config_unreadable",
    "wiki_schema_missing",
    "wiki_schema_invalid",
    "wiki_schema_legacy",
)


def count_reasons(root: Path, since: str = "") -> dict[str, int]:
    """Occurrences of each reason code across <root>/*/trace.jsonl, only rows with ts >= since (ISO, UTC) when given.

    Unreadable or torn input counts as nothing.
    """
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
            code = cast("dict[str, Any]", row).get("reason_code") if isinstance(row, dict) else None
            stamp = cast("dict[str, Any]", row).get("ts") if isinstance(row, dict) else None
            if since and not (isinstance(stamp, str) and stamp >= since):
                continue
            if isinstance(code, str) and code in counts:
                counts[code] += 1
    return counts


def main() -> int:
    """Print the counts as JSON for the loop dir (CLAUDE_AGENTIC_LOOP_DIR or the default); --since <ISO ts> scopes."""
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv[:-1] else ""
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    print(json.dumps(count_reasons(root, since), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
