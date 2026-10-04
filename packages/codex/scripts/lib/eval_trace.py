"""Append-only, fail-open, NON-AUTHORITATIVE trace rows for eval refusals and grandfathered passes.

Sink: eval_trace.jsonl beside the evals.json it describes (so it is not loop-safe: PR-scope files live
wherever the caller put them). Nothing reads these rows to decide a grade. Inputs are sha256 only.
Field names match the shared trace helper in the open stacked PRs #478-#479.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, cast

SCHEMA_VERSION = 1


def _read(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def emit(evals_path: str | Path, command: str, outcome: str, reason_code: str) -> None:
    """Append one row; never raises."""
    try:
        path = Path(evals_path)
        progress = _read(path.with_name("progress.json"))
        ident = {**_read(path), **{k: progress[k] for k in ("session_id", "loop_id") if k in progress}}
        row = {
            "schema_version": SCHEMA_VERSION,
            "session_id": ident.get("session_id"),
            "loop_id": ident.get("loop_id"),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "command": command,
            "outcome": outcome,
            "reason_code": reason_code,
            "event_id": str(uuid.uuid4()),
            "inputs": {"evals_sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        }
        with open(path.with_name("eval_trace.jsonl"), "a", encoding="utf-8") as sink:
            sink.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - fail-open by contract
        return
