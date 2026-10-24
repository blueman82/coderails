"""Controller commands `start` and `add-unit`: the only writers of a loop's initial state and work units.

Each is one lock and one atomic replace. Every outcome carries a closed reason code and a non-authoritative trace row.
"""

from __future__ import annotations

import copy
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .graph_executor import graph_contract, graph_semantics, graph_spec, transition
from .graph_recovery import RecoveryRefusedError, trace
from .loop_state_common import atomic_progress_update

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/agentic-loop/scripts"))
from graph_convert import STATE_MINOR
from graph_vocab import validate_disposition

UNIT_ID = re.compile(r"[1-9][0-9]*")


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
        "stops": [],
        "state_minor": STATE_MINOR,
        "graph": {
            "nodes": {},
            "edges": [],
            "joins": {},
            "active_wave": None,
            "hard_stop": None,
            "wave_history": {},
            "dispatches": {},
            "contract_from_revision": 1,
        },
    }


def record_unit(path: Path, session: str, unit_id: str, status: str, detail: str) -> dict[str, Any]:
    """Record an independently checked work-unit decision through the Claude lock."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        if state["session_id"] != session:
            raise ValueError("session does not own this graph")
        if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
            raise ValueError("work unit requires an in-progress graph without an active wave")
        units = cast(object, state.get("work_units"))
        if not unit_id.strip() or not isinstance(units, dict):
            raise ValueError("work unit must be registered")
        unit = cast(dict[str, object], units).get(unit_id)
        if not isinstance(unit, dict):
            raise ValueError("work unit must be registered and pending")
        record = cast(dict[str, object], unit)
        if record.get("status") != "pending":
            raise ValueError("work unit must be registered and pending")
        if status not in {"done", "dropped"} or not detail.strip():
            raise ValueError("work unit decision requires a status and nonblank evidence or reason")
        record["status"] = status
        record["evidence" if status == "done" else "dropped_reason"] = detail.strip()
        output.update(unit=unit_id, status=status, revision=state["revision"])
        return state

    transition(path, update)
    return output


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


def register_unit(
    state: dict[str, Any],
    unit: str,
    deps: list[str],
    join: bool,
    manifest: list[str] | None = None,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a copy of `state` with the unit's spec lane, dependency edges and unit-join inputs added."""
    spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
    node_id = graph_spec.unit_root_id(spec, unit)
    if not UNIT_ID.fullmatch(unit):
        raise RecoveryRefusedError("add_unit_refused_bad_id", "unit id must match [1-9][0-9]*")
    units, graph = state.get("work_units"), state["graph"]
    if not isinstance(units, dict):
        raise RecoveryRefusedError("add_unit_refused_state", "work_units is not an object", (node_id,))
    added = graph_spec.lane(spec, policy, state, unit, join)
    if unit in units or any(identifier in graph["nodes"] for identifier in added["nodes"]):
        raise RecoveryRefusedError("add_unit_refused_duplicate", f"unit {unit} is already registered", (node_id,))
    unknown = [d for d in deps if d not in units or graph_spec.unit_root_id(spec, d) not in graph["nodes"]]
    if unknown:
        raise RecoveryRefusedError("add_unit_refused_unknown_dep", f"unknown dependency {unknown}", (node_id,))
    proposed = copy.deepcopy(state)
    proposed["revision"] += 1  # the graph changed: evals frozen at the old revision must go STALE
    graph = proposed["graph"]
    stored = {"status": "pending", **({"manifest": manifest} if manifest else {}), **(fields or {})}
    proposed["work_units"][unit] = stored
    graph["nodes"].update(added["nodes"])
    graph["edges"].extend({"from": graph_spec.unit_root_id(spec, d), "to": node_id} for d in dict.fromkeys(deps))
    graph["edges"].extend({"from": source, "to": target} for source, target in added["edges"])
    gate_spec = added["join"]
    if gate_spec["inputs"]:
        gate_id = gate_spec["id"]
        gate = graph["joins"].setdefault(gate_id, {"id": gate_id, "mode": "all", "inputs": [], "released": False})
        if gate["released"]:
            raise RecoveryRefusedError("add_unit_refused_state", f"{gate_id} is already released", (node_id,))
        gate["inputs"].extend(gate_spec["inputs"])
        graph["nodes"].setdefault(gate_id, gate_spec["node"])
    for gate_id, found in added["other_joins"].items():
        if graph["joins"][gate_id]["released"]:
            raise RecoveryRefusedError("add_unit_refused_state", f"{gate_id} is already released", (node_id,))
        graph["joins"][gate_id]["inputs"].extend(found)
    return proposed


def add_unit(
    path: Path,
    session: str,
    loop_id: str,
    unit: str,
    deps: list[str],
    join: bool,
    manifest: list[str] | None = None,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register one work unit and its graph wiring in one locked, kernel-validated save.

    `contract` holds optional dispatch inputs, a publication base branch, and `disposition`:
    a (kind, named_blocker, removal_ticket) triple validated by graph_vocab.
    """
    inputs: dict[str, Any] = {"session": session, "loop_id": loop_id, "unit": unit, "deps": deps, "join": join}
    ident = {"session_id": session, "loop_id": loop_id}
    spec = graph_spec.load_spec()
    refusal: list[RecoveryRefusedError] = []
    revision: list[int] = []
    given = contract or {}
    try:
        fields = graph_contract.unit_fields(
            given.get("model_role"),
            given.get("write_scope", []),
            given.get("lessons", []),
            given.get("scope"),
            given.get("base_branch"),
            given.get("worktree"),
        )
    except ValueError as error:
        coded = RecoveryRefusedError("add_unit_refused_bad_field", str(error))
        raise _refused("add-unit", path, ident, coded, inputs) from error
    try:
        stored = validate_disposition(*given.get("disposition", (None, None, None)))
    except ValueError as error:
        coded = RecoveryRefusedError("add_unit_refused_disposition", str(error))
        raise _refused("add-unit", path, ident, coded, inputs) from error
    if stored:
        fields["disposition"] = stored

    def update(state: dict[str, Any]) -> dict[str, Any]:
        try:
            if state["session_id"] != session or state["loop_id"] != loop_id:
                raise RecoveryRefusedError("add_unit_refused_foreign", "session or loop does not own this graph")
            if state["status"] != "in-progress" or state["graph"]["active_wave"] is not None:
                message = "add-unit needs an in-progress loop with no active wave"
                raise RecoveryRefusedError("add_unit_refused_state", message)
            proposed = register_unit(state, unit, deps, join, manifest, fields)
            try:
                graph_semantics.validate(proposed)
            except graph_semantics.GraphSemanticError as error:
                code = "add_unit_refused_cycle" if error.code == "cycle" else "add_unit_refused_state"
                raise RecoveryRefusedError(code, error.message, (graph_spec.unit_root_id(spec, unit),)) from error
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
    node_id = graph_spec.unit_root_id(spec, unit)
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
        "depends_on": list(dict.fromkeys(deps)),
        "joined": join,
        "revision": revision[0],
        "reason_code": "add_unit_registered",
    }


def instantiate(path: Path, session: str, loop_id: str, profile: str | None, units: list[str]) -> dict[str, Any]:
    """Build the spec's graph into an empty started loop under the lock; re-runs no-op, foreign graphs are refused."""
    chosen: str = profile or graph_spec.load_policy()["graph"]["profile"]
    inputs: dict[str, Any] = {"session": session, "loop_id": loop_id, "profile": chosen, "units": units}
    ident = {"session_id": session, "loop_id": loop_id}
    outcome: list[dict[str, Any]] = []
    refusal: list[RecoveryRefusedError] = []

    def update(state: dict[str, Any]) -> dict[str, Any]:
        try:
            proposed, report = graph_spec.instantiate(state, session, loop_id, chosen, units)
        except graph_spec.SpecError as error:
            refusal.append(RecoveryRefusedError(error.code, error.message))
            raise refusal[0] from error
        outcome.append(report)
        if report["status"] == "noop":
            raise _NoopError
        return proposed

    try:
        transition(path, update)
    except ValueError as error:
        if not (outcome and outcome[0]["status"] == "noop"):
            coded = refusal[0] if refusal else RecoveryRefusedError("instantiate_refused_state", str(error))
            raise _refused("instantiate", path, ident, coded, inputs) from error
    report = outcome[0]
    trace(
        path,
        {**ident, "revision": report["revision"], "graph": {}},
        report["status"],
        report["reason_code"],
        inputs,
        [],
        "instantiate",
    )
    return report
