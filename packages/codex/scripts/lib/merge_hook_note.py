"""Read a recent hook-consumed receipt note before merge.py claims execution."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, cast

from scripts.lib import action_receipt as ar


def fresh(path: Path, number: str, window: int) -> dict[str, Any] | None:
    """Return a recent note for this PR when the receipt is not yet executed."""
    marker = path.with_suffix(".consumed")
    try:
        raw: object = json.loads(marker.read_text(encoding="utf-8"))
        recent = time.time() - marker.stat().st_mtime <= window
    except (OSError, ValueError, RecursionError):
        return None
    note = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    return note if note.get("number") == number and recent and not ar.is_executed(path) else None
