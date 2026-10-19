"""Recover a Claude wave whose spawned workers are all silent, bounded by retry.max, in one locked save.

A node with no native spawn is only reported ("spawn it now"): nothing is ever recorded for it. Recovery uses the
existing `stale` outcome plus `respawn_stale`, so every attempt keeps a native tool_use_id reference.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict, cast

from .graph_evidence import child_identity, notifications, records, spawns, transcript, validate_child_terminal
from .graph_evidence_bind import bind_wave
from .graph_executor import graph_semantics, load, transition

TRACE_NAME = "recovery-trace.jsonl"
NODE_CODES = {"dispatch": "no_spawn_dispatch", "record": "worker_finished_record", "waiting": "worker_waiting"}


class CollectionRecord(TypedDict):
    """Validated index entry describing one graph and its outgoing graph links."""

    key: str
    path: str
    loop_id: str
    links: list[str]


class RecoveryRefusedError(ValueError):
    """A fail-closed recover-wave refusal carrying one stable, low-cardinality reason code."""

    def __init__(self, reason_code: str, message: str, nodes: tuple[str, ...] = ()) -> None:
        """Keep the closed-enum code, the implicated nodes and the bare message; str() shows the code to operators."""
        super().__init__(f"{message} [reason_code={reason_code}]")
        self.reason_code, self.message, self.nodes = reason_code, message, nodes


Rows = Sequence[tuple["str | None", "int | None", "str | None"]]


def _attempt(state: dict[str, Any], node_id: str) -> int:
    """The attempt number the node's next spawn carries."""
    node = state["graph"]["nodes"][node_id]
    return int(node["retry"]["attempts"] + node["respawn"]["generation"] + 1)


def trace(
    path: Path,
    state: dict[str, Any],
    outcome: str,
    code: str,
    inputs: dict[str, Any],
    rows: Rows,
    command: str = "recover-wave",
) -> None:
    """Append non-authoritative rows beside the state. Never read back; never raises or alters a transition."""
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


def _refuse(
    path: Path, state: dict[str, Any], error: RecoveryRefusedError, inputs: dict[str, Any]
) -> RecoveryRefusedError:
    """Trace a refusal naming the implicated nodes, then return the coded error for the caller to raise."""
    rows: Rows = [(n, _attempt(state, n), None) for n in error.nodes if n in state["graph"]["nodes"]]
    trace(path, state, "refused", error.reason_code, inputs, rows)
    return error


def _spent(node: dict[str, Any]) -> bool:
    """True when the node's respawn generation has reached its retry max."""
    return bool(node["respawn"]["generation"] >= node["retry"]["max"])


def _row_state(session: str, row: dict[str, Any], path: Path, notices: dict[str, Any], now: float, lease: int) -> str:
    """Classify one native spawn: record (finished or launch refused), waiting or stalled."""
    result = row["native_result"]
    if result.get("is_error") is True and not result.get("agentId"):
        return "record"
    agent = child_identity(path, session, row, False)
    if any(item["status"] == "completed" for item in notices.get(row["tool_use_id"], [])):
        return "record"
    entries = records(path.with_suffix("") / "subagents" / f"agent-{agent}.jsonl")
    try:
        validate_child_terminal(entries)
        return "record"
    except ValueError:
        pass
    stamp = datetime.fromisoformat(str(entries[-1]["timestamp"]).replace("Z", "+00:00")).timestamp()
    return "stalled" if now - stamp >= lease else "waiting"


def classify(state: dict[str, Any], now: float, lease: int) -> dict[str, str]:
    """Classify every active-wave node: dispatch, record, waiting or stalled. Anything unreadable is refused."""
    active = state["graph"]["active_wave"]
    try:
        path = transcript(state["session_id"])
        rows, notices = spawns(path, state["session_id"]), notifications(path, state["session_id"])
        result: dict[str, str] = {}
        for node_id in active["nodes"]:
            mine = [
                row
                for row in rows
                if row["node_id"] == node_id
                and row["wave_id"] == active["wave_id"]
                and row["line"] > active["transcript_cursor"]
            ]
            try:
                states = {_row_state(state["session_id"], row, path, notices, now, lease) for row in mine}
            except (ValueError, KeyError, IndexError, TypeError) as error:
                message = f"transcript for {node_id} is unreadable: {error}"
                raise RecoveryRefusedError("unreadable_transcript", message, (node_id,)) from error
            if not mine:
                result[node_id] = "dispatch"
            elif "record" in states:
                result[node_id] = "record"
            else:
                result[node_id] = "stalled" if states == {"stalled"} else "waiting"
        return result
    except RecoveryRefusedError:
        raise
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise RecoveryRefusedError("unreadable_transcript", f"transcript is unreadable: {error}") from error


def _plan(
    path: Path, state: dict[str, Any], session: str, lease: int, clock: float, inputs: dict[str, object]
) -> tuple[dict[str, str], dict[str, Any]]:
    """Classify the wave and build its report, refusing foreign sessions, absent waves and unreadable evidence."""
    if state["session_id"] != session:
        raise _refuse(path, state, RecoveryRefusedError("foreign_session", "session does not own this graph"), inputs)
    active = state["graph"]["active_wave"]
    if active is None:
        raise _refuse(path, state, RecoveryRefusedError("no_active_wave", "no active wave exists"), inputs)
    try:
        nodes = classify(state, clock, lease)
    except RecoveryRefusedError as error:
        raise _refuse(path, state, error, inputs) from error
    kinds = set(nodes.values())
    uniform = len(kinds) == 1 and "stalled" not in kinds
    return nodes, {
        "wave_id": active["wave_id"],
        "nodes": {node_id: {"action": action} for node_id, action in nodes.items()},
        "recovered": False,
        "reason_code": (
            NODE_CODES[next(iter(kinds))] if uniform else ("stalled_report_only" if len(kinds) == 1 else "mixed_wave")
        ),
    }


def _stale_wave(state: dict[str, Any], nodes: dict[str, str], lease: int) -> dict[str, Any]:
    """Record the wave `stale` with native bound references and request every respawn, writing nothing."""
    check = {"checked": True, "method": f"lease {lease}s expired", "result": "no worker activity"}
    results = {n: {"outcome": "stale", "evidence": "lease expired", "stale_check": check} for n in nodes}
    wave_id = state["graph"]["active_wave"]["wave_id"]
    proposed = cast(dict[str, Any], graph_semantics.record_wave(state, wave_id, results)["state"])
    for node_id, refs in bind_wave(state, results).items():
        proposed["graph"]["nodes"][node_id]["evidence"].extend(refs)
    for node_id in nodes:
        proposed = cast(dict[str, Any], graph_semantics.respawn_stale(proposed, node_id, "lease expired")["state"])
    return proposed


def recover_wave(
    path: Path, session: str, lease_seconds: int, now: float | None = None, apply: bool = True
) -> dict[str, Any]:
    """Recover an active wave whose every spawned worker is silent past the lease, in one locked save."""
    if lease_seconds <= 0:  # a non-positive lease marks every live worker stalled
        raise RecoveryRefusedError("invalid_lease", "lease_seconds must be positive")
    clock = time.time() if now is None else now
    state = load(path)
    inputs: dict[str, object] = {"session": session, "lease": lease_seconds, "now": clock, "apply": apply}
    nodes, report = _plan(path, state, session, lease_seconds, clock, inputs)
    inputs["nodes"] = nodes
    rows: list[tuple[str | None, int | None, str | None]] = [
        (n, _attempt(state, n), action) for n, action in nodes.items()
    ]
    if not apply or set(nodes.values()) != {"stalled"}:
        trace(path, state, "reported", report["reason_code"], inputs, rows)
        return report
    refusal: list[RecoveryRefusedError] = []
    seen: list[dict[str, Any]] = []  # the locked state, so a refusal is traced from it, never the pre-read
    traced: list[RecoveryRefusedError] = []  # refusals _plan already traced

    def update(locked: dict[str, Any]) -> dict[str, Any]:
        seen.append(locked)
        try:
            try:
                current, _ = _plan(path, locked, session, lease_seconds, clock, inputs)
            except RecoveryRefusedError as error:
                traced.append(error)
                raise
            rows[:] = [
                (n, _attempt(locked, n), action) for n, action in current.items()
            ]  # the locked attempt, not the pre-read
            moved = tuple(n for n, action in current.items() if action != "stalled")
            if moved:
                raise RecoveryRefusedError("mixed_wave", "wave changed before recovery could be recorded", moved)
            spent = tuple(n for n in current if _spent(locked["graph"]["nodes"][n]))
            if spent:
                message = "recovery budget exhausted: waiting for human"
                raise RecoveryRefusedError("recovery_budget_exhausted", message, spent)
            return _stale_wave(locked, current, lease_seconds)
        except RecoveryRefusedError as error:
            refusal.append(error)
            raise

    try:
        transition(path, update)
    except ValueError as error:
        if refusal:
            raise (refusal[0] if refusal[0] in traced else _refuse(path, seen[-1], refusal[0], inputs)) from error
        raise
    report.update(recovered=True, reason_code="recovered")
    trace(path, state, "recovered", "recovered", inputs, rows)
    return report


def summarize(state: dict[str, Any]) -> dict[str, Any]:
    """Plain-language status from graph state alone: done, active, ready, blocked and the human dependency."""
    graph = state["graph"]
    statuses = {node_id: node["status"] for node_id, node in graph["nodes"].items()}
    pending = sorted(n for n, s in statuses.items() if s not in {"done", "skipped"})
    ready = [] if graph["active_wave"] or graph["hard_stop"] else graph_semantics.ready(state)
    if graph["hard_stop"] is not None:
        phase, detail = (
            "waiting for human",
            f"hard stop on {graph['hard_stop']['node']}: {graph['hard_stop']['reason']}",
        )
    elif graph["active_wave"] is not None:
        phase, detail = "waiting for worker", f"wave {graph['active_wave']['wave_id']} dispatched"
        spent = [n for n in graph["active_wave"]["nodes"] if _spent(graph["nodes"][n])]
        if spent:
            detail += f"; recovery budget exhausted for {', '.join(spent)}: recover-wave will refuse, a human decides"
    elif ready:
        phase, detail = "ready to dispatch", "begin-wave then spawn the ready nodes"
    elif not pending:
        phase, detail = "ready to complete", "run verify-completion"
    else:
        phase, detail = "waiting for evidence", "no node is ready; check pending dependencies"
    return {
        "phase": phase,
        "detail": detail,
        "done": sorted(n for n in statuses if n not in pending),
        "active": list(graph["active_wave"]["nodes"]) if graph["active_wave"] else [],
        "ready": ready,
        "pending": pending,
    }


def collection(root: Path) -> dict[str, Any]:
    """List validated graph states beneath a directory without changing them."""
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("graph collection root must be a directory")
    graphs_by_path: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("progress.json")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError(f"graph state escapes collection root: {path}")
        state = load(path)
        graph = state["graph"]
        relative = path.relative_to(root).as_posix()
        if state["loop_id"] in {item["loop_id"] for item in graphs_by_path.values()}:
            raise ValueError(f"duplicate graph loop_id {state['loop_id']!r}; collection keys must be unambiguous")
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
    if index_path.is_symlink() or not index_path.resolve().is_relative_to(root):
        raise ValueError("collection index escapes collection root")
    if index_path.exists():
        try:
            raw_index: object = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid collection index {index_path}: {error}") from error
        if not isinstance(raw_index, dict):
            raise ValueError("collection index must contain schema_version 1 and a graphs array")
        index = cast(dict[str, Any], raw_index)
        if index.get("schema_version") != 1 or not isinstance(index.get("graphs"), list):
            raise ValueError("collection index must contain schema_version 1 and a graphs array")
        by_key: dict[str, CollectionRecord] = {}
        by_path: dict[str, CollectionRecord] = {}
        for raw_record in cast(list[Any], index["graphs"]):
            if not isinstance(raw_record, dict):
                raise ValueError("each collection graph must be an object")
            entry = cast(dict[str, object], raw_record)
            if not all(field in entry for field in ("key", "path", "loop_id", "links")):
                raise ValueError("each collection graph needs nonblank key, path, loop_id and string links")
            key_value, path_value, loop_id_value, links = (
                entry["key"],
                entry["path"],
                entry["loop_id"],
                entry["links"],
            )
            if not all(isinstance(value, str) and value for value in (key_value, path_value, loop_id_value)):
                raise ValueError("each collection graph needs nonblank key, path, loop_id and string links")
            if not isinstance(links, list):
                raise ValueError("each collection graph needs nonblank key, path, loop_id and string links")
            link_values = cast(list[object], links)
            for raw_target in link_values:
                if not isinstance(raw_target, str) or not raw_target:
                    raise ValueError("each collection graph needs nonblank key, path, loop_id and string links")
            key, record_path, loop_id = cast(str, key_value), cast(str, path_value), cast(str, loop_id_value)
            targets = cast(list[str], links)
            if key in by_key:
                raise ValueError(f"duplicate graph key {key!r}")
            if record_path in by_path:
                raise ValueError(f"duplicate graph path {record_path!r}")
            if record_path not in graphs_by_path or graphs_by_path[record_path]["loop_id"] != loop_id:
                raise ValueError(f"collection record {key!r} does not match a discovered graph at {record_path!r}")
            registered: CollectionRecord = {"key": key, "path": record_path, "loop_id": loop_id, "links": targets}
            by_key[key], by_path[record_path] = registered, registered
        if set(by_path) != set(graphs_by_path):
            missing = sorted(set(graphs_by_path) - set(by_path))
            raise ValueError(f"collection index omits discovered graph path(s): {', '.join(missing)}")
        for key, record in by_key.items():
            if len(record["links"]) != len(set(record["links"])):
                raise ValueError(f"duplicate graph link on {key!r}")
            for target in record["links"]:
                if target not in by_key:
                    raise ValueError(f"unknown graph link target {target!r} from {key!r}")
            graph = graphs_by_path[record["path"]]
            graph["key"], graph["links"] = key, list(record["links"])
    return {"graphs": [graphs_by_path[path] for path in sorted(graphs_by_path)], "unresolved_targets": []}
