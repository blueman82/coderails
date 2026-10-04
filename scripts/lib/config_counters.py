"""Count typed-config and wiki-schema reason codes from per-session trace rows (read-only)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

REASONS = ("config_unknown_key", "config_bad_type", "config_unreadable", "wiki_schema_missing", "wiki_schema_invalid")


def count_reasons(root: Path) -> dict[str, int]:
    """Occurrences of each reason code across <root>/*/trace.jsonl; unreadable or torn input counts as nothing."""
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
            if isinstance(code, str) and code in counts:
                counts[code] += 1
    return counts


def main() -> int:
    """Print the counts as JSON for the loop dir (CLAUDE_AGENTIC_LOOP_DIR or the default)."""
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    print(json.dumps(count_reasons(root), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
