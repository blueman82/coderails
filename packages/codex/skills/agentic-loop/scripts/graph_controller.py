"""Controller commands `start` and `add-unit`: the only writers of a loop's initial state and work units.

Each is one lock and one atomic replace. Every outcome carries a closed reason code and a non-authoritative trace row.
Mirrors the Claude adapter's behaviour; the provider-parity tests pin the two together.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import graph_contract
import graph_semantics
import graph_spec
from graph_convert import STATE_MINOR
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import write as _write
from graph_recovery import RecoveryRefusedError, trace
from graph_vocab import validate_disposition

UNIT_ID = re.compile(r"[1-9][0-9]*")


def _refused(
    command: str, path: Path, ident: dict[str, Any], error: RecoveryRefusedError, inputs: dict[str, Any]
) -> RecoveryRefusedError:
    """Trace a refusal, then hand the coded error back for the caller to raise."""
    rows = [(error.nodes[0], None, None)] if error.nodes else []
    trace(path, ident, "refused", error.reason_code, inputs, rows, command)
    return error


def _stub(session: str, loop_id: str, prompt: str) -> dict[str, Any]:
    """The schema-v3 initial state: in-progress, empty graph."""
    return {
        "schema_version": 3,
        "session_id": session,
        "loop_id": loop_id,
        "revision": 1,
        "status": "in-progress",
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "authorising_prompt_raw": prompt,
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
    try:
        with _locked(path, create=True):
            status, code = _decide(path, session, loop_id, prompt)
    except RecoveryRefusedError as error:
        raise _refused("start", path, ident, error, inputs) from error
    except (OSError, ValueError) as error:
        message = f"progress.json is locked or unreadable: {error}"
        raise _refused("start", path, ident, RecoveryRefusedError("start_refused_path", message), inputs) from error
    trace(path, {**ident, "revision": 1, "graph": {}}, status, code, inputs, [], "start")
    return {"status": status, "reason_code": code, "session_id": session, "loop_id": loop_id, "revision": 1}


def _decide(path: Path, session: str, loop_id: str, prompt: str) -> tuple[str, str]:
    """Under the lock: create, no-op, re-arm or refuse."""
    raw: object = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError("existing state is not an object")
    existing = cast(dict[str, Any], raw)
    if not existing:
        _write(path, _stub(session, loop_id, prompt), create=True)
        return "created", "start_created"
    if existing.get("session_id") != session:
        raise RecoveryRefusedError("start_refused_session", "progress.json belongs to another session")
    if existing.get("loop_id") == loop_id:
        if existing.get("status") == "complete":
            raise RecoveryRefusedError("start_refused_loop_complete", "loop is complete: start with a fresh --loop-id")
        return "noop", "start_noop"
    if existing.get("status") != "complete":
        message = "an unfinished loop owns this session: resume it (inspect, summarize), do not restart"
        raise RecoveryRefusedError("start_refused_active_loop", message)
    _write(path, _stub(session, loop_id, prompt))
    return "rearmed", "start_rearmed"


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
    stored = {
        "status": "pending",
        "registered_revision": proposed["revision"],
        **({"manifest": manifest} if manifest else {}),
        **(fields or {}),
    }
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
    node_id = graph_spec.unit_root_id(graph_spec.load_spec(), unit)
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
        fields.update(graph_contract.source_assignment(fields.get("worktree"), manifest or []))
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
    try:
        with _locked(path):
            state = _load(path)
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
                raise RecoveryRefusedError(code, error.message, (node_id,)) from error
            _write(path, proposed)
    except RecoveryRefusedError as error:
        raise _refused("add-unit", path, ident, error, inputs) from error
    except (OSError, ValueError) as error:
        coded = RecoveryRefusedError("add_unit_refused_state", str(error))
        raise _refused("add-unit", path, ident, coded, inputs) from error
    done: dict[str, Any] = {**ident, "revision": proposed["revision"], "graph": {}}
    trace(path, done, "registered", "add_unit_registered", inputs, [(node_id, 1, None)], "add-unit")
    return {
        "unit": unit,
        "node": node_id,
        "depends_on": list(dict.fromkeys(deps)),
        "joined": join,
        "revision": proposed["revision"],
        "reason_code": "add_unit_registered",
    }


def assign_worktree(path: Path, session: str, loop_id: str, unit: str, worktree: str) -> dict[str, Any]:
    """Assign a checkout to an existing unit under the Codex graph lock."""
    ident = {"session_id": session, "loop_id": loop_id}
    inputs = {"unit": unit, "worktree": worktree}
    try:
        assigned = graph_contract.unit_fields(None, [], [], None, worktree=worktree)["worktree"]
        with _locked(path):
            state = _load(path)
            units: object = state.get("work_units")
            raw: object = cast(dict[str, object], units).get(unit) if isinstance(units, dict) else None
            record = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
            if state["session_id"] != session or state["loop_id"] != loop_id or state["status"] != "in-progress":
                raise ValueError("loop ownership or status mismatch")
            if record is None or record.get("status") != "pending":
                raise ValueError("unit is not pending")
            if record.get("worktree") not in (None, assigned):
                raise ValueError("unit already has another worktree")
            record.update(graph_contract.source_assignment(assigned, record.get("manifest", [])))
            graph_semantics.validate(state)
            _write(path, state)
    except (OSError, ValueError) as error:
        coded = RecoveryRefusedError("assign_worktree_refused", str(error))
        raise _refused("assign-worktree", path, ident, coded, inputs) from error
    trace(path, ident, "assigned", "worktree_assigned", inputs, [], "assign-worktree")
    return {"unit": unit, "worktree": assigned, "reason_code": "worktree_assigned"}


def set_unit_disposition(
    path: Path,
    session: str,
    loop_id: str,
    revision: int,
    unit: str,
    kind: str,
    named_blocker: str | None,
    removal_ticket: str | None,
    source_ref: str | None,
) -> dict[str, Any]:
    """Record one sourced compatibility choice on a pending unit under the Codex graph lock."""
    ident = {"session_id": session, "loop_id": loop_id}
    inputs = {"unit": unit, "revision": revision, "disposition": kind, "source_ref": source_ref}
    try:
        choice = validate_disposition(kind, named_blocker, removal_ticket)
        source = (source_ref or "").strip()
        if not source or len(source) > 500 or "\n" in source or "\r" in source:
            raise ValueError("a single-line source reference is required")
        with _locked(path):
            state = _load(path)
            units = state.get("work_units")
            raw: object = cast(dict[str, object], units).get(unit) if isinstance(units, dict) else None
            record = cast(dict[str, Any], raw) if isinstance(raw, dict) else None
            if state.get("session_id") != session or state.get("loop_id") != loop_id:
                raise ValueError("session or loop does not own this graph")
            if state.get("status") != "in-progress" or state.get("revision") != revision:
                raise ValueError("loop status or revision changed")
            if state["graph"].get("active_wave") is not None:
                raise ValueError("an active wave holds this graph")
            if record is None or record.get("status") != "pending" or record.get("disposition") is not None:
                raise ValueError("unit is absent, not pending, or already has a choice")
            proposed = copy.deepcopy(state)
            proposed["revision"] += 1
            proposed["work_units"][unit].update(
                disposition=choice, disposition_source=source, disposition_revision=proposed["revision"]
            )
            graph_semantics.validate(proposed)
            _write(path, proposed)
    except (OSError, ValueError) as error:
        coded = RecoveryRefusedError("set_disposition_refused", str(error))
        raise _refused("set-unit-disposition", path, ident, coded, inputs) from error
    trace(path, proposed, "recorded", "unit_disposition_recorded", inputs, [], "set-unit-disposition")
    return {
        "unit": unit,
        "disposition": choice,
        "revision": proposed["revision"],
        "reason_code": "unit_disposition_recorded",
    }


def instantiate(path: Path, session: str, loop_id: str, profile: str | None, units: list[str]) -> dict[str, Any]:
    """Build the spec's graph into an empty started loop under the lock; re-runs no-op, foreign graphs are refused."""
    chosen: str = profile or graph_spec.load_policy()["graph"]["profile"]
    inputs: dict[str, Any] = {"session": session, "loop_id": loop_id, "profile": chosen, "units": units}
    ident = {"session_id": session, "loop_id": loop_id}
    try:
        with _locked(path):
            proposed, report = graph_spec.instantiate(_load(path), session, loop_id, chosen, units)
            if report["status"] == "created":
                graph_semantics.validate(proposed)
                graph_spec.check(proposed)
                _write(path, proposed)
    except graph_spec.SpecError as error:
        raise _refused("instantiate", path, ident, RecoveryRefusedError(error.code, error.message), inputs) from error
    except (OSError, ValueError) as error:
        coded = RecoveryRefusedError("instantiate_refused_state", str(error))
        raise _refused("instantiate", path, ident, coded, inputs) from error
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
