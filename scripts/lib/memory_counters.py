"""Count memory-adapter trace rows (`memory.*`) by reason_code, once per event_id; counts only, never row inputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast


def memory_counts(roots: list[Path]) -> dict[str, Any]:
    """Return {"rows": n, "by_reason_code": {code: n}} over trace rows whose command starts `memory.`."""
    seen: set[str] = set()
    by_reason: dict[str, int] = {}
    for path in sorted({p.resolve() for root in roots for p in root.glob("*/trace.jsonl")}):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                loaded: Any = json.loads(line)
            except ValueError:
                continue
            if not isinstance(loaded, dict):
                continue
            row = cast("dict[str, Any]", loaded)
            if not str(row.get("command", "")).startswith("memory."):
                continue
            event_id = row.get("event_id")
            if isinstance(event_id, str) and event_id and event_id not in seen:
                seen.add(event_id)
                code = str(row.get("reason_code"))
                by_reason[code] = by_reason.get(code, 0) + 1
    return {"rows": len(seen), "by_reason_code": dict(sorted(by_reason.items()))}
