"""Classify an active wave's workers for recovery, and append the non-authoritative recovery trace."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

from graph_data import event_payload, read_records
from graph_identity import GraphError, next_attempt, task_name
from graph_io import load as _load
from graph_transcript import child_read_records, parent_indexes, refused_launches, thread_transcript


class RecoveryRefusedError(GraphError):
    """A fail-closed recover-wave refusal carrying one stable, low-cardinality reason code."""

    def __init__(self, reason_code: str, message: str, nodes: tuple[str, ...] = (), attempt: int | None = None) -> None:
        """Keep the closed-enum code, the implicated nodes, the refused attempt (if known) and the bare message."""
        super().__init__(f"{message} [reason_code={reason_code}]")
        self.reason_code, self.message, self.nodes, self.attempt = reason_code, message, nodes, attempt


class CollectionRecord(TypedDict):
    """Validated collection index record for one graph and its outgoing links."""

    key: str
    path: str
    loop_id: str
    links: list[str]


def collection(root: Path) -> dict[str, Any]:
    """List validated graph states beneath a directory without changing them."""
    root = root.resolve()
    if not root.is_dir():
        raise GraphError("graph collection root must be a directory")
    graphs_by_path: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("progress.json")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise GraphError(f"graph state escapes collection root: {path}")
        state = _load(path)
        graph = state["graph"]
        relative = path.relative_to(root).as_posix()
        if state["loop_id"] in {item["loop_id"] for item in graphs_by_path.values()}:
            raise GraphError(f"duplicate graph loop_id {state['loop_id']!r}; collection keys must be unambiguous")
        graphs_by_path[relative] = {
            "key": state["loop_id"],
            "path": relative,
            "loop_id": state["loop_id"],
            "session_id": state["session_id"],
            "revision": state["revision"],
            "status": state["status"],
            "nodes": [
                {"id": node_id, "name": node["label"], "status": node["status"]}
                for node_id, node in sorted(graph["nodes"].items())
            ],
            "links": [],
        }
    index_path = root / "collection.json"
    if index_path.exists():
        try:
            raw_index: object = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise GraphError(f"invalid collection index {index_path}: {error}") from error
        if not isinstance(raw_index, dict):
            raise GraphError("collection index must contain schema_version 1 and a graphs array")
        index = cast(dict[str, Any], raw_index)
        if index.get("schema_version") != 1 or not isinstance(index.get("graphs"), list):
            raise GraphError("collection index must contain schema_version 1 and a graphs array")
        by_key: dict[str, CollectionRecord] = {}
        by_path: dict[str, CollectionRecord] = {}
        for raw_record in cast(list[Any], index["graphs"]):
            if not isinstance(raw_record, dict):
                raise GraphError("each collection graph must be an object")
            entry = cast(dict[str, object], raw_record)
            if not all(field in entry for field in ("key", "path", "loop_id", "links")):
                raise GraphError("each collection graph needs nonblank key, path, loop_id and string links")
            key_value, path_value, loop_id_value, links = (
                entry["key"],
                entry["path"],
                entry["loop_id"],
                entry["links"],
            )
            if not all(isinstance(value, str) and value for value in (key_value, path_value, loop_id_value)):
                raise GraphError("each collection graph needs nonblank key, path, loop_id and string links")
            if not isinstance(links, list):
                raise GraphError("each collection graph needs nonblank key, path, loop_id and string links")
            link_values = cast(list[object], links)
            for raw_target in link_values:
                if not isinstance(raw_target, str) or not raw_target:
                    raise GraphError("each collection graph needs nonblank key, path, loop_id and string links")
            key, record_path, loop_id = cast(str, key_value), cast(str, path_value), cast(str, loop_id_value)
            targets = cast(list[str], links)
            if key in by_key:
                raise GraphError(f"duplicate graph key {key!r}")
            if record_path in by_path:
                raise GraphError(f"duplicate graph path {record_path!r}")
            if record_path not in graphs_by_path or graphs_by_path[record_path]["loop_id"] != loop_id:
                raise GraphError(f"collection record {key!r} does not match a discovered graph at {record_path!r}")
            registered: CollectionRecord = {"key": key, "path": record_path, "loop_id": loop_id, "links": targets}
            by_key[key], by_path[record_path] = registered, registered
        if set(by_path) != set(graphs_by_path):
            missing = sorted(set(graphs_by_path) - set(by_path))
            raise GraphError(f"collection index omits discovered graph path(s): {', '.join(missing)}")
        for key, record in by_key.items():
            if len(record["links"]) != len(set(record["links"])):
                raise GraphError(f"duplicate graph link on {key!r}")
            for target in record["links"]:
                if target not in by_key:
                    raise GraphError(f"unknown graph link target {target!r} from {key!r}")
            graph = graphs_by_path[record["path"]]
            graph["key"], graph["links"] = key, list(record["links"])
    return {"graphs": [graphs_by_path[path] for path in sorted(graphs_by_path)], "unresolved_targets": []}


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
def traced_refusal(
    path: Path, state: dict[str, Any], command: str, session: str | None = None
) -> Generator[None, None, None]:
    """Trace any coded refusal raised inside the block as one `refused` row, then let it propagate unchanged."""
    try:
        yield
    except RecoveryRefusedError as error:
        rows = [(node, error.attempt, None) for node in error.nodes]
        trace(path, state, "refused", error.reason_code, {"session": session}, rows, command)
        raise
