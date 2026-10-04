"""Controller commands `start` and `add-unit`: the only writers of a loop's initial state and work units.

Each is one lock and one atomic replace. Every outcome carries a closed reason code and a non-authoritative trace row.
"""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .graph_executor import graph_semantics, transition
from .graph_recovery import RecoveryRefusedError, trace
from .loop_state_common import atomic_progress_update

UNIT_ID = re.compile(r"[1-9][0-9]*")
JOIN = "J12-all-units"


class _NoopError(ValueError):
    """Internal: the file already holds this loop, so nothing is written."""


def _refused(
    command: str, path: Path, ident: dict[str, Any], error: RecoveryRefusedError, inputs: dict[str, Any]
) -> RecoveryRefusedError:
    """Trace a refusal, then hand the coded error back for the caller to raise."""
    rows = [(error.nodes[0], None, None)] if error.nodes else []
    trace(path, ident, "refused", error.reason_code, inputs, rows, command)
    return error


def _stub(session: str, loop_id: str, prompt: str, marker: object) -> dict[str, Any]:
    """The schema-v3 initial state: in-progress, empty graph."""
    return {
        "schema_version": 3,
        "session_id": session,
        "loop_id": loop_id,
        "revision": 1,
        "status": "in-progress",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "authorising_prompt_raw": prompt,
        "completed_marker": marker,
        "work_units": {},
        "graph": {"nodes": {}, "edges": [], "joins": {}, "active_wave": None, "hard_stop": None},
    }


def start(path: Path, session: str, loop_id: str, prompt_file: Path) -> dict[str, Any]:
    """Create, no-op or re-arm the session-owned stub under the lock; refuse to overwrite a live loop."""
    try:
        prompt = Path(prompt_file).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot read prompt file: {error}") from error
    inputs: dict[str, Any] = {
        "session": session,
        "loop_id": loop_id,
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    }
    ident = {"session_id": session, "loop_id": loop_id}
    if not loop_id.strip():
        raise ValueError("loop-id must be non-blank")
    if not session.strip() or session == "?":
        message = "a blank or ? session cannot own a loop"
        raise _refused("start", path, ident, RecoveryRefusedError("start_refused_session", message), inputs)
    if path.name != "progress.json" or path.parent.name != session:
        message = f"state path must end <session>/progress.json, got {path}"
        raise _refused("start", path, ident, RecoveryRefusedError("start_refused_path", message), inputs)
    outcome: list[tuple[str, str]] = []
    refusal: list[RecoveryRefusedError] = []

    def update(existing: dict[str, Any]) -> dict[str, Any]:
        if not existing:
            outcome.append(("created", "start_created"))
            return _stub(session, loop_id, prompt, 0)
        try:
            if existing.get("session_id") != session:
                raise RecoveryRefusedError("start_refused_session", "progress.json belongs to another session")
            if existing.get("loop_id") == loop_id:
                if existing.get("status") == "complete":
                    raise RecoveryRefusedError(
                        "start_refused_loop_complete", "loop is complete: start with a fresh --loop-id"
                    )
                outcome.append(("noop", "start_noop"))
                raise _NoopError
            if existing.get("status") != "complete":
                message = "an unfinished loop owns this session: resume it (inspect, summarize), do not restart"
                raise RecoveryRefusedError("start_refused_active_loop", message)
        except RecoveryRefusedError as error:
            refusal.append(error)
            raise
        outcome.append(("rearmed", "start_rearmed"))
        return _stub(session, loop_id, prompt, existing.get("completed_marker", 0))

    saved = atomic_progress_update(path, update, create=True)
    if refusal:
        raise _refused("start", path, ident, refusal[0], inputs)
    if not saved and not (outcome and outcome[0][0] == "noop"):
        message = "progress.json is locked or unreadable"
        raise _refused("start", path, ident, RecoveryRefusedError("start_refused_path", message), inputs)
    status, code = outcome[0]
    trace(path, {**ident, "revision": 1, "graph": {}}, status, code, inputs, [], "start")
    return {"status": status, "reason_code": code, "session_id": session, "loop_id": loop_id, "revision": 1}


def register_unit(state: dict[str, Any], unit: str, deps: list[str], join: bool) -> dict[str, Any]:
    """Return a copy of `state` with the work unit, its U3 node, dependency edges and optional J12 input added."""
    node_id = f"U3[{unit}]"
    if not UNIT_ID.fullmatch(unit):
        raise RecoveryRefusedError("add_unit_refused_bad_id", "unit id must match [1-9][0-9]*")
    units, graph = state.get("work_units"), state["graph"]
    if not isinstance(units, dict):
        raise RecoveryRefusedError("add_unit_refused_state", "work_units is not an object", (node_id,))
    if unit in units or node_id in graph["nodes"]:
        raise RecoveryRefusedError("add_unit_refused_duplicate", f"unit {unit} is already registered", (node_id,))
    unknown = [d for d in deps if d not in units or f"U3[{d}]" not in graph["nodes"]]
    if unknown:
        raise RecoveryRefusedError("add_unit_refused_unknown_dep", f"unknown dependency {unknown}", (node_id,))
    proposed = copy.deepcopy(state)
    proposed["revision"] += 1  # the graph changed: evals frozen at the old revision must go STALE
    graph = proposed["graph"]
    proposed["work_units"][unit] = {"status": "pending"}
    fresh: dict[str, Any] = {
        "status": "pending",
        "outcome": "pending",
        "retry": {"attempts": 0, "max": 5},
        "evidence": [],
    }
    graph["nodes"][node_id] = {"label": f"Build unit {unit}", **fresh, "respawn": {"generation": 0, "intent": None}}
    graph["edges"].extend({"from": f"U3[{d}]", "to": node_id} for d in dict.fromkeys(deps))
    if join:
        gate = graph["joins"].setdefault(JOIN, {"id": JOIN, "mode": "all", "inputs": [], "released": False})
        if gate["released"]:
            raise RecoveryRefusedError("add_unit_refused_state", f"{JOIN} is already released", (node_id,))
        gate["inputs"].append(node_id)
        graph["nodes"].setdefault(
            JOIN,
            {"label": graph_semantics.LABELS[JOIN], **fresh, "respawn": {"generation": 0, "intent": None}},
        )
    return proposed


def add_unit(path: Path, session: str, loop_id: str, unit: str, deps: list[str], join: bool) -> dict[str, Any]:
    """Register one work unit and its graph wiring in one locked, kernel-validated save."""
    inputs: dict[str, Any] = {"session": session, "loop_id": loop_id, "unit": unit, "deps": deps, "join": join}
    ident = {"session_id": session, "loop_id": loop_id}
    refusal: list[RecoveryRefusedError] = []
    revision: list[int] = []

    def update(state: dict[str, Any]) -> dict[str, Any]:
        try:
            if state["session_id"] != session or state["loop_id"] != loop_id:
                raise RecoveryRefusedError("add_unit_refused_foreign", "session or loop does not own this graph")
            if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
                message = "add-unit needs an in-progress loop with no active wave"
                raise RecoveryRefusedError("add_unit_refused_state", message)
            proposed = register_unit(state, unit, deps, join)
            try:
                graph_semantics.validate(proposed)
            except graph_semantics.GraphSemanticError as error:
                code = "add_unit_refused_cycle" if error.code == "cycle" else "add_unit_refused_state"
                raise RecoveryRefusedError(code, error.message, (f"U3[{unit}]",)) from error
        except RecoveryRefusedError as error:
            refusal.append(error)
            raise
        revision.append(proposed["revision"])
        return proposed

    try:
        transition(path, update)
    except ValueError as error:
        coded = refusal[0] if refusal else RecoveryRefusedError("add_unit_refused_state", str(error))
        raise _refused("add-unit", path, ident, coded, inputs) from error
    node_id = f"U3[{unit}]"
    trace(
        path,
        {**ident, "revision": revision[0], "graph": {}},
        "registered",
        "add_unit_registered",
        inputs,
        [(node_id, 1, None)],
        "add-unit",
    )
    return {
        "unit": unit,
        "node": node_id,
        "depends_on": deps,
        "joined": join,
        "revision": revision[0],
        "reason_code": "add_unit_registered",
    }
