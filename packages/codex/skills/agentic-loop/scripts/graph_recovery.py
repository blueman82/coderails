"""Classify an active wave's workers for recovery, and append the non-authoritative recovery trace."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from graph_data import event_payload, read_records
from graph_identity import GraphError, next_attempt, task_name
from graph_transcript import child_read_records, parent_indexes, refused_launches, thread_transcript


class RecoveryRefusedError(GraphError):
    """A fail-closed recover-wave refusal carrying one stable, low-cardinality reason code."""

    def __init__(self, reason_code: str, message: str, nodes: tuple[str, ...] = ()) -> None:
        """Keep the closed-enum code, the implicated nodes and the bare message; str() shows the code to operators."""
        super().__init__(f"{message} [reason_code={reason_code}]")
        self.reason_code, self.message, self.nodes = reason_code, message, nodes


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
        refused = [item for item in refused_launches(parent).values() if item[0] > cursor and item[1] == expected]
        if not found and not refused:
            return "dispatch"
        states: set[str] = {"record"} if refused else set()  # a refused launch is recordable, as in the Claude provider
        for _, _, child, nickname, path, role in found:
            records = child_read_records(state["session_id"], child, nickname, path, role)
            if any(event_payload(record).get("type") == "task_complete" for _, record in records):
                states.add("record")
                continue
            stamp = datetime.fromisoformat(str(records[-1][1]["timestamp"]).replace("Z", "+00:00")).timestamp()
            states.add("stalled" if now - stamp >= lease else "waiting")
    except (GraphError, KeyError, IndexError, ValueError, TypeError) as error:
        message = f"node {node_id} transcript is unreadable: {error}"
        raise RecoveryRefusedError("unreadable_transcript", message, (node_id,)) from error
    # any record wins; stalled only when every spawn is stalled (mirrors the Claude classify)
    if "record" in states:
        return "record"
    if states != {"stalled"}:
        return "waiting"
    if len(found) > 1:  # unlike Claude, stale evidence binding here needs exactly one spawn per task name
        message = f"node {node_id} has {len(found)} silent spawns for {expected}; stale evidence needs exactly one"
        raise RecoveryRefusedError("ambiguous_spawn", message, (node_id,))
    return "stalled"


NODE_CODES = {"dispatch": "no_spawn_dispatch", "record": "worker_finished_record", "waiting": "worker_waiting"}
TRACE_NAME = "recovery-trace.jsonl"


Rows = Sequence[tuple["str | None", "int | None", "str | None"]]


def trace(
    path: Path,
    state: dict[str, Any],
    outcome: str,
    code: str,
    inputs: dict[str, Any],
    rows: Rows,
    command: str = "recover-wave",
) -> None:
    """Append non-authoritative rows next to the state. Never read back; never raises or alters a transition."""
    try:
        graph = cast("dict[str, Any]", state.get("graph") or {})
        active = cast("dict[str, Any] | None", graph.get("active_wave"))
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
        base: dict[str, Any] = {
            "schema_version": 1,
            "event_id": uuid.uuid4().hex,  # one per event: a wave over N nodes writes N rows sharing it
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": state.get("session_id"),
            "caller_session": inputs.get("session"),
            "loop_id": state.get("loop_id"),
            "wave_id": active["wave_id"] if active else None,
            "revision": state.get("revision"),
            "command": command,
            "outcome": outcome,
            "reason_code": code,
            "inputs_sha256": digest,
        }
        lines = [
            json.dumps({**base, "node_id": node, "attempt": attempt, "node_action": action}, sort_keys=True)
            for node, attempt, action in rows or [(None, None, None)]
        ]
        with path.with_name(TRACE_NAME).open("a", encoding="utf-8") as sidecar:
            sidecar.write("".join(line + "\n" for line in lines))
    except Exception:  # noqa: BLE001 - fail open: the trace is advisory
        return


@contextmanager
def traced_refusal(path: Path, state: dict[str, Any], command: str) -> Generator[None, None, None]:
    """Trace any coded refusal raised inside the block as one `refused` row, then let it propagate unchanged."""
    try:
        yield
    except RecoveryRefusedError as error:
        rows = [(node, None, None) for node in error.nodes]
        trace(path, state, "refused", error.reason_code, {"session": state.get("session_id")}, rows, command)
        raise
