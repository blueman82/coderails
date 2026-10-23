"""Own Claude graph dispatch envelopes and atomic native-evidence transitions."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

from .graph_evidence import cursor, object_value, transcript
from .graph_evidence_bind import bind_wave
from .graph_evidence_revalidate import revalidate_all
from .graph_executor import (
    ROOT,
    graph_contract,
    graph_repair,
    graph_semantics,
    graph_spec,
    load,
    transition,
    validate_state,
)
from .graph_recovery import recover_wave as recover_wave
from .graph_recovery import trace
from .graph_stops import record_stop
from .loop_completion import validate_completion
from .loop_evals import EvalStatus, read_loop_evals
from .loop_state_common import LoopState, read_state

sys.path.insert(0, str(ROOT))
import worker_status  # noqa: E402

from scripts.lib.config import config_path, load_config  # noqa: E402
from scripts.lib.config_strict import sandbox_mode, strict_settings  # noqa: E402


def validate_dispatch_evals(path: Path, state: dict[str, Any], node_id: str, worker: bool = False) -> None:
    """Require session-bound frozen eval authority for implementation dispatch."""
    if graph_spec.before_freeze(graph_spec.load_spec(), node_id) and not worker:
        return
    units = state.get("work_units", {})
    if not isinstance(units, dict):
        raise ValueError("work_units must be a current-schema object")
    if not units:
        return
    suite = read_state(path.with_name("evals.json"))
    if any(suite.get(key) != state[key] for key in ("session_id", "loop_id")):
        raise ValueError("frozen eval suite belongs to another session or loop")
    verdict = read_loop_evals(path.parent)
    if verdict.status not in {EvalStatus.GO, EvalStatus.VERIFICATION_LEVEL0, EvalStatus.FROZEN}:
        raise ValueError(f"dispatch requires frozen loop evals before build; current verdict: {verdict.label}")


def wave_record(state: dict[str, Any], node_id: str) -> tuple[str, dict[str, Any]] | None:
    """The begin-wave dispatch record (id, record) for a node of the active wave, or None."""
    active = state["graph"]["active_wave"]
    records = state["graph"].get("dispatches", {})
    return next(
        (
            (identifier, record)
            for identifier, record in records.items()
            if active and record["node_id"] == node_id and record["wave_id"] == active["wave_id"]
        ),
        None,
    )


def add_records(proposed: dict[str, Any], base: str, mode: str, path: Path) -> None:
    """Store one dispatch record (contract, sections digest, single-use slot) per node of the just-opened wave."""
    graph = proposed["graph"]
    wave = graph["active_wave"]
    for node_id in wave["nodes"]:
        node = graph["nodes"][node_id]
        attempt = node["retry"]["attempts"] + node["respawn"]["generation"] + 1
        contract = graph_contract.build_contract(proposed, node_id, base, path, ROOT / "scripts/push.py")
        identifier, record = graph_contract.make_record(
            proposed, node_id, wave["wave_id"], attempt, contract, mode if contract["role"] == "loop-worker" else None
        )
        graph.setdefault("dispatches", {})[identifier] = record


def plan(path: Path) -> list[dict[str, Any]]:
    """Resolve graph instruction sources without imposing custom provider roles."""
    state = load(path)
    nodes = state["graph"]["active_wave"]["nodes"] if state["graph"]["active_wave"] else graph_semantics.ready(state)
    result: list[dict[str, Any]] = []
    config = config_path()
    settings = strict_settings(config) if config else load_config("")[0]
    mode = sandbox_mode(settings)  # sandbox_workers has a typed code reader here
    spec, policy = graph_spec.load_spec(), graph_spec.load_policy()
    for node_id in nodes:
        role = state["graph"]["nodes"][node_id].get("graph_role") or graph_spec.split_id(node_id)[0]
        entry = graph_spec.role_node(spec, role)
        source = entry["source"] if entry else None
        item: dict[str, Any] = {
            "node_id": node_id,
            "graph_role": role,
            "path": source,
            "unresolved": not source or not (ROOT / source).is_file(),
        }
        if entry and entry["agent_role"] == "loop-worker":
            item["dispatch_mode"] = mode
        spec_node = graph_spec.node_for(spec, node_id)
        if spec_node and spec_node["skip_when"]:
            item["skip_when_met"] = graph_spec.skip_when_met(state, spec, policy, node_id)
        found = wave_record(state, node_id)
        if found:
            item["dispatch_id"] = found[0]
            item["prompt_prefix"] = graph_contract.prompt_prefix(state, *found)
            item["prompt_sections"] = graph_contract.render_sections(found[1]["contract"])
        result.append(item)
    met = [(item["node_id"], None, None) for item in result if item.get("skip_when_met")]
    if met:  # counted by scripts/lib/spec_counters.py: one row per node whose skip predicate held at plan time
        trace(path, state, "reported", "skip_when_met", {"units": len(state["work_units"])}, met, "plan")
    return result


def begin_wave(path: Path) -> dict[str, Any]:
    """Open exactly the core-ready wave and capture its native transcript boundary."""
    base, mode = graph_contract.base_ref(), sandbox_mode(load_config(config_path())[0])

    def update(state: dict[str, Any]) -> dict[str, Any]:
        graph_contract.require_converted(state)
        for node in graph_semantics.ready(state):
            validate_dispatch_evals(path, state, node)
        proposed = object_value(graph_semantics.begin_wave(state)["state"], "proposed graph")
        active = proposed["graph"]["active_wave"]
        boundary = cursor(state["session_id"])
        active["transcript_cursor"] = boundary
        history = proposed["graph"].setdefault("wave_history", {})
        history[active["wave_id"]] = {
            "cursor": boundary,
            "nodes": list(active["nodes"]),
            "revision": active["revision"],
        }
        add_records(proposed, base, mode, path)
        return proposed

    state = transition(path, update)
    return {**state["graph"]["active_wave"], "dispatches": plan(path)}


def record_wave(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Bind actual native evidence and collect a whole wave in one locked write."""
    if set(report) != {"wave_id", "results"}:
        raise ValueError("wave report must contain exactly wave_id and results")
    results = object_value(report["results"], "wave results")
    response: dict[str, Any] = {}
    refusal: list[worker_status.WorkerResultError] = []
    recorded: list[list[dict[str, Any]]] = []

    def update(state: dict[str, Any]) -> dict[str, Any]:
        try:
            core, statuses, reports = worker_status.prepare(state, results)
        except worker_status.WorkerResultError as error:
            refusal.append(error)
            raise
        proposal = graph_semantics.record_wave(state, report["wave_id"], core)
        references = bind_wave(state, core)
        proposed = object_value(proposal["state"], "proposed graph")
        worker_status.retain_decision_slot(proposed, statuses)
        graph_repair.apply_failed_gates(proposal, core)
        for node_id, refs in references.items():
            proposed["graph"]["nodes"][node_id]["evidence"].extend(refs)
        worker_status.record_into(proposed, report["wave_id"], statuses, reports)
        if statuses:  # one typed stop row on the post-record state, in the same locked write
            category, code, reason = worker_status.stop_for(statuses)
            proposed = object_value(
                record_stop(proposed, state["session_id"], category, code, reason)["state"], "stops"
            )
        recorded.append(statuses + [{"node": node, "status": "FINAL_REPORT"} for node in reports])
        response.update(
            {
                "revision": proposed["revision"],
                "released_joins": proposal["released_joins"],
                "ready": graph_semantics.ready(proposed),
            }
        )
        return proposed

    try:
        transition(path, update)
    except ValueError:
        if refusal:
            trace(path, load(path), "refused", refusal[0].code, {}, [(refusal[0].node, None, None)], "record-wave")
            raise refusal[0] from None
        raise
    if recorded[0]:
        state = load(path)
        for item in recorded[0]:
            code = (
                "final_report_recorded"
                if item["status"] == "FINAL_REPORT"
                else f"worker_status_{item['status'].lower()}"
            )
            trace(path, state, "recorded", code, {}, [(item["node"], None, None)], "record-wave")
    return response


def authorize_dispatch(
    path: Path, session: str, prompt: str, role: str, tool_use_id: str | None = None
) -> dict[str, Any]:
    """Validate the actual native Agent request against its begin-wave record, assert the role, consume the id.

    Every check runs under the state lock before anything is written; a refusal leaves progress.json untouched and
    leaves one coded trace row. `tool_use_id` (from the PreToolUse payload, unverified) makes a hook retry idempotent.
    """
    state = load(path)
    if state["session_id"] != session or state["status"] == "complete":
        raise ValueError("this session does not own an active loop")
    role = role.strip()
    inputs = {"session": session, "role": role}
    if not role:
        error = graph_contract.DispatchDeniedError("role_mismatch", "native Agent requires subagent_type")
        trace(path, state, "refused", error.code, inputs, [(None, None, None)], "authorize-dispatch")
        raise error
    if graph_contract.dispatch_off():
        try:
            graph_contract.require_converted(state)
            request = graph_contract.parse_envelope(prompt)
            record = graph_contract.check_ownership(state, request, live=True)
            graph_contract.require_publication(record, path, ROOT / "scripts/push.py")
            validate_dispatch_evals(path, state, request["node_id"], role == "coderails:loop-worker")
        except graph_contract.DispatchDeniedError as error:
            trace(path, state, "refused", error.code, inputs, [(None, None, None)], "authorize-dispatch")
            raise
        trace(
            path,
            state,
            "reported",
            "dispatch_check_off",
            inputs,
            [(request["node_id"], None, None)],
            "authorize-dispatch",
        )
        return request
    denied: list[graph_contract.DispatchDeniedError] = []
    granted: list[dict[str, Any]] = []
    named: list[str | None] = [None]  # the envelope's node, once it parses, for the trace row

    def update(current: dict[str, Any]) -> dict[str, Any]:
        try:
            graph_contract.require_converted(current)
            request = graph_contract.parse_envelope(prompt)
            named[0] = request["node_id"]
            record = graph_contract.check_dispatch(current, request, prompt, live=True)
            graph_contract.require_publication(record, path, ROOT / "scripts/push.py")
            graph_contract.assert_role(record["contract"], role, "coderails:", graph_contract.CLAUDE_TYPES)
            validate_dispatch_evals(path, current, request["node_id"], role == "coderails:loop-worker")
            used = record["authorized"]
            if used is not None and not (tool_use_id and used.get("tool_use_id") == tool_use_id):
                raise graph_contract.DispatchDeniedError("dispatch_replayed", "dispatch envelope was already used")
            record["authorized"] = {"tool_use_id": tool_use_id}
            granted.append(request)
        except graph_contract.DispatchDeniedError as error:
            denied.append(error)
            raise
        return current

    try:
        transition(path, update)
    except ValueError:
        if not denied:
            raise
        trace(path, state, "refused", denied[0].code, inputs, [(named[0], None, None)], "authorize-dispatch")
        raise denied[0] from None
    trace(path, state, "authorized", "dispatch_authorized", inputs, [(named[0], None, None)], "authorize-dispatch")
    return granted[0]


def validate_graph_shape(path: Path) -> None:
    """Fail closed unless the complete current native graph is valid."""
    load(path)


def validate_graph_state_completion(state: dict[str, Any], session: str) -> None:
    """Check pure graph eligibility and re-derive every native worker reference."""
    validate_state(state)
    if state["session_id"] != session:
        raise ValueError("session does not own this graph")
    eligibility = graph_semantics.can_complete(state)
    if not eligibility["eligible"]:
        raise ValueError("graph cannot complete: " + ", ".join(eligibility["blockers"]))
    revalidate_all(state)


def validate_graph_completion(path: Path, session: str) -> None:
    """Read and validate graph completion for the native Stop hook."""
    try:
        validate_graph_state_completion(load(path), session)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"malformed native graph evidence: {error}") from error


def validate_artifacts(path: Path, state: dict[str, Any]) -> None:
    """Require current identity-bound graded evals, retrospective and actual proofs."""
    session = state["session_id"]
    filenames = ["evals.json", "retro.json"]
    if path.with_name("proof.json").exists():
        filenames.append("proof.json")
    for filename in filenames:
        artifact = read_state(path.with_name(filename))
        if any(artifact.get(key) != state[key] for key in ("session_id", "loop_id")):
            raise ValueError(f"{filename} belongs to another session or loop")
    suite = read_state(path.with_name("evals.json"))
    grading = object_value(suite.get("grading"), "eval grading")
    if (
        suite.get("revision") != state["revision"]
        or grading.get("by") != "post_evals.py grade-loop"
        or grading.get("amendments_at_grade") != len(suite.get("amendments", []))
        or read_loop_evals(path.parent).status is not EvalStatus.GO
    ):
        raise ValueError("loop evals lack current neutral GO grading")
    retro = read_state(path.with_name("retro.json"))
    if retro.get("status") != "complete":
        raise ValueError("retrospective must describe completion")
    validate_completion(LoopState(path, session, 0, state), str(transcript(session)))


def complete(path: Path, session: str, write: bool = True) -> dict[str, Any]:
    """Validate all native gates under the state lock before completion is written."""

    def update(state: dict[str, Any]) -> dict[str, Any]:
        validate_graph_state_completion(state, session)
        validate_artifacts(path, state)
        proposed = copy.deepcopy(state)
        proposed["status"] = "complete"
        return proposed

    state = transition(path, update) if write else update(load(path))
    return {"session_id": session, "loop_id": state["loop_id"], "status": state["status"]}
