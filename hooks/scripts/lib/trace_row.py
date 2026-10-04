#!/usr/bin/env python3
"""Non-authoritative, fail-open, append-only trace rows beside session loop state."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def trace_path(session_id: str, base: Path | None = None) -> Path | None:
    """Return <loop dir>/<session_id>/trace.jsonl, or None for an id that is empty or not path-local.

    Unsafe ids are refused rather than sanitised so two distinct ids can never share a file.
    """
    if not session_id or session_id in {"?", "."} or "/" in session_id or ".." in session_id or "\0" in session_id:
        return None
    root = base or Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    return root / session_id / "trace.jsonl"


def append_row(
    command: str,
    outcome: str,
    reason_code: str,
    session_id: str,
    loop_id: str | None = None,
    inputs: dict[str, Any] | None = None,
    base: Path | None = None,
) -> bool:
    """Append one JSON row with a single O_APPEND write; never raises. Inputs are stored only as sha256."""
    path = trace_path(session_id, base)
    if path is None:
        return False
    row = {
        "schema_version": SCHEMA_VERSION,
        "event_id": str(uuid.uuid4()),
        "session_id": session_id,
        "loop_id": loop_id,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": command,
        "outcome": outcome,
        "reason_code": reason_code,
        "inputs": {k: hashlib.sha256(str(v).encode("utf-8")).hexdigest() for k, v in (inputs or {}).items()},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError:
        return False
    return True
