"""Count capability reason codes from per-session trace rows (read-only; counts only, never row content)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, cast

REASONS = (
    "capability_args_invalid",
    "capability_path_denied",
    "capability_bad_ref",
    "capability_no_repo",
    "capability_tests_unknown_name",
    "capability_sandbox_unavailable",
    "capability_profiles_invalid",
    "capability_io_error",
    "capability_unknown_tool",
    "capability_bad_argv",
    "capability_wrong_role",
    "capability_mcp_refused",
)


def count_reasons(root: Path, since: str = "") -> dict[str, int]:
    """Counts of each refusal code plus `ok` (successful calls) over <root>/*/trace.jsonl rows of command `capability`.

    Only rows with ts >= since (ISO, UTC) when given; unreadable or torn input counts as nothing.
    """
    counts: dict[str, int] = dict.fromkeys((*REASONS, "ok"), 0)
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
            if not isinstance(row, dict) or cast("dict[str, Any]", row).get("command") != "capability":
                continue
            fields = cast("dict[str, Any]", row)
            stamp = fields.get("ts")
            if since and not (isinstance(stamp, str) and stamp >= since):
                continue
            key = "ok" if fields.get("outcome") == "ok" else fields.get("reason_code")
            if isinstance(key, str) and key in counts:
                counts[key] += 1
    return counts


def main() -> int:
    """Print the counts as JSON for the loop dir (CLAUDE_AGENTIC_LOOP_DIR or the default); --since <ISO ts> scopes."""
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv[:-1] else ""
    root = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    print(json.dumps(count_reasons(root, since), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
