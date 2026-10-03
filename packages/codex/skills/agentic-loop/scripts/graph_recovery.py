"""Classify an active wave's workers for recovery, and append the non-authoritative recovery trace."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from graph_data import event_payload, read_records
from graph_identity import GraphError, next_attempt, task_name
from graph_transcript import child_read_records, parent_indexes, thread_transcript


class RecoveryRefusedError(GraphError):
    """A fail-closed recover-wave refusal carrying one stable, low-cardinality reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        """Keep the closed-enum code beside the human message."""
        super().__init__(message)
        self.reason_code = reason_code


def node_lease(state: dict[str, Any], node_id: str, active: dict[str, Any], now: float, lease: int) -> str:
    """Classify one active-wave node: dispatch, record, waiting or stalled. Anything unreadable is refused."""
    try:
        parent = read_records(thread_transcript(state["session_id"]), "parent transcript")
        expected = task_name(state["loop_id"], node_id, next_attempt(state["graph"]["nodes"][node_id]))
        cursor = active["transcript_cursor"]
        found = [
            item
            for calls in parent_indexes(parent).values()
            for item in calls
            if item[0] > cursor and item[1] == expected
        ]
        if not found:
            return "dispatch"
        if len(found) > 1:
            raise GraphError(f"node {node_id} has more than one spawn for {expected}")
        _, _, child, nickname, path, role = found[0]
        records = child_read_records(state["session_id"], child, nickname, path, role)
        if any(event_payload(record).get("type") == "task_complete" for _, record in records):
            return "record"
        stamp = datetime.fromisoformat(str(records[-1][1]["timestamp"]).replace("Z", "+00:00")).timestamp()
    except (GraphError, KeyError, IndexError, ValueError, TypeError) as error:
        message = f"node {node_id} transcript is unreadable: {error}"
        raise RecoveryRefusedError("unreadable_transcript", message) from error
    return "stalled" if now - stamp >= lease else "waiting"


NODE_CODES = {"dispatch": "no_spawn_dispatch", "record": "worker_finished_record", "waiting": "worker_waiting"}
TRACE_NAME = "recovery-trace.jsonl"


def trace(
    path: Path, state: dict[str, Any], outcome: str, code: str, inputs: object, nodes: dict[str, int | None]
) -> None:
    """Append non-authoritative rows next to the state. Never read back; never raises or alters a transition."""
    try:
        active = cast("dict[str, Any] | None", state["graph"]["active_wave"])
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
        base: dict[str, Any] = {
            "schema_version": 1,
            "session_id": state.get("session_id"),
            "loop_id": state.get("loop_id"),
            "wave_id": active["wave_id"] if active else None,
            "revision": state.get("revision"),
            "command": "recover-wave",
            "outcome": outcome,
            "reason_code": code,
            "inputs_sha256": digest,
        }
        rows = [{**base, "node_id": node, "attempt": attempt} for node, attempt in (nodes or {"": None}).items()]
        for row in rows:
            row["node_id"] = row["node_id"] or None
        with path.with_name(TRACE_NAME).open("a", encoding="utf-8") as sidecar:
            sidecar.write("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    except Exception:  # noqa: BLE001 - fail open: the trace is advisory
        return
