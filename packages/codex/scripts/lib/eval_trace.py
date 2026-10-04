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
MAX_SINK_BYTES = 1_048_576  # ponytail: hard cap, no rotation; past it rows are dropped (fail-open)


def _read(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _row(line: str) -> dict[str, Any]:
    try:
        value: object = json.loads(line)
    except ValueError:
        return {}
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def emit(evals_path: str | Path, command: str, outcome: str, reason_code: str) -> None:
    """Append one row; never raises."""
    try:
        path = Path(evals_path)
        progress = _read(path.with_name("progress.json"))
        ident = {**_read(path), **{k: progress[k] for k in ("session_id", "loop_id") if k in progress}}
        sink_path = path.with_name("eval_trace.jsonl")
        evals_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if sink_path.exists():
            if sink_path.stat().st_size > MAX_SINK_BYTES:
                return
            # One row per (suite state, command, outcome, reason): hook polling must not inflate counters.
            for line in sink_path.read_text(encoding="utf-8").splitlines():
                old = _row(line)
                inputs = cast(dict[str, Any], old.get("inputs") or {})
                seen = (old.get("command"), old.get("outcome"), old.get("reason_code"), inputs.get("evals_sha256"))
                if seen == (command, outcome, reason_code, evals_sha):
                    return
        row = {
            "schema_version": SCHEMA_VERSION,
            "session_id": ident.get("session_id"),
            "loop_id": ident.get("loop_id"),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "command": command,
            "outcome": outcome,
            "reason_code": reason_code,
            "event_id": str(uuid.uuid4()),
            "inputs": {"evals_sha256": evals_sha},
        }
        with open(sink_path, "a", encoding="utf-8") as sink:
            sink.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception:  # noqa: BLE001 - fail-open by contract
        return
