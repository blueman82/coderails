"""Advisory trace rows and event_id-deduped counters for external_enforcement and ci_verify.

Fail-open and non-authoritative: a missing or unwritable trace never changes a command's exit code.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.trace_row import append_row

SESSION = "external-enforcement"
COMMANDS = ("external_enforcement.plan", "external_enforcement.apply", "ci_verify.run")


def emit(command: str, reason_code: str) -> None:
    """Append one advisory row; outcome is `ok` for success codes and `refused` otherwise."""
    ok = reason_code in {"DRY_RUN", "NO_DIFF", "APPLIED", "OK"}
    append_row(command, "ok" if ok else "refused", reason_code, SESSION, inputs={"command": command})


def enforcement_counts(roots: list[Path]) -> dict[str, Any]:
    """Count rows per `command/reason_code` once per event_id across roots; counts only, no row content."""
    seen: set[str] = set()
    by_reason: dict[str, int] = {}
    duplicates = malformed = 0
    for path in dict.fromkeys(root / SESSION / "trace.jsonl" for root in roots):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
                event_id, command = row["event_id"], row["command"]
                key = f"{command}/{row['reason_code']}"
            except (ValueError, KeyError, TypeError):
                malformed += 1
                continue
            if command not in COMMANDS or not isinstance(event_id, str):
                malformed += 1
            elif event_id in seen:
                duplicates += 1
            else:
                seen.add(event_id)
                by_reason[key] = by_reason.get(key, 0) + 1
    return {"events": len(seen), "duplicates": duplicates, "malformed": malformed, "by_reason": by_reason}
