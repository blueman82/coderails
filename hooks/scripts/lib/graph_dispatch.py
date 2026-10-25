"""Own Claude graph dispatch envelopes and atomic native-evidence transitions."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path
from typing import Any

from scripts.lib import orders_completion

from .dir_lock import acquire_dir_lock, release_dir_lock
from .graph_evidence import ENVELOPE_KEY, cursor, envelope, object_value, transcript
from .graph_evidence_bind import bind_wave
from .graph_evidence_revalidate import revalidate_all
from .graph_executor import ROOT, graph_repair, graph_semantics, graph_spec, load, transition, validate_state
from .graph_recovery import recover_wave as recover_wave
from .graph_recovery import trace
from .loop_completion import validate_completion
from .loop_evals import EvalStatus, read_loop_evals
from .loop_state_common import LoopState, read_state

sys.path.insert(0, str(ROOT))
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


def ownership(state: dict[str, Any], node_id: str) -> dict[str, Any]:
    """Describe the exact native wave and node a worker is authorized to execute."""
    active = object_value(state["graph"]["active_wave"], "active wave")
    return {
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "revision": state["revision"],
        "wave_id": active["wave_id"],
        "node_id": node_id,
    }


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
            **graph_semantics.describe_node(node_id),
            "graph_role": role,
            "path": source,
            "unresolved": not source or not (ROOT / source).is_file(),
        }
        if entry and entry["agent_role"] == "loop-worker":
            item["dispatch_mode"] = mode
        spec_node = graph_spec.node_for(spec, node_id)
        if spec_node and spec_node["skip_when"]:
            item["skip_when_met"] = graph_spec.skip_when_met(state, spec, policy, node_id)
        if state["graph"]["active_wave"]:
            item["prompt_prefix"] = ENVELOPE_KEY + "=" + json.dumps(ownership(state, node_id), sort_keys=True)
            item["node_name_marker"] = "CODERAILS_GRAPH_NODE_NAME=" + item["display"]
        result.append(item)
    met = [(item["node_id"], None, None) for item in result if item.get("skip_when_met")]
    if met:  # counted by scripts/lib/spec_counters.py: one row per node whose skip predicate held at plan time
        trace(path, state, "reported", "skip_when_met", {"units": len(state["work_units"])}, met, "plan")
    return result


def begin_wave(path: Path) -> dict[str, Any]:
    """Open exactly the core-ready wave and capture its native transcript boundary."""

    def update(state: dict[str, Any]) -> dict[str, Any]:
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
        return proposed

    state = transition(path, update)
    return {**state["graph"]["active_wave"], "dispatches": plan(path)}


def record_wave(path: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Bind actual native evidence and collect a whole wave in one locked write."""
    if set(report) != {"wave_id", "results"}:
        raise ValueError("wave report must contain exactly wave_id and results")
    results = object_value(report["results"], "wave results")
    response: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        proposal = graph_semantics.record_wave(state, report["wave_id"], results)
        graph_repair.apply_failed_gates(proposal, results)
        references = bind_wave(state, results)
        proposed = object_value(proposal["state"], "proposed graph")
        for node_id, refs in references.items():
            proposed["graph"]["nodes"][node_id]["evidence"].extend(refs)
        response.update(
            {"revision": proposed["revision"], "released_joins": proposal["released_joins"], "ready": proposal["ready"]}
        )
        return proposed

    transition(path, update)
    return response


def authorize_dispatch(path: Path, session: str, prompt: str, role: str) -> dict[str, Any]:
    """Validate the actual native Agent request against the active graph owner."""
    state = load(path)
    if state["session_id"] != session or state["status"] == "complete":
        raise ValueError("this session does not own an active loop")
    if not role.strip():
        raise ValueError("native Agent requires its provider subagent_type")
    request = envelope(prompt)
    active = object_value(state["graph"]["active_wave"], "active wave")
    node_id = request["node_id"]
    if node_id not in active["nodes"] or request != ownership(state, node_id):
        raise ValueError("dispatch envelope does not own an exact node in the active wave")
    validate_dispatch_evals(path, state, node_id, role == "coderails:loop-worker")
    return request


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


def complete(path: Path, session: str, write: bool = True, completed_marker: int | None = None) -> dict[str, Any]:
    """Prepare orders, save validated completion, then apply the lifecycle outside both locks."""
    current = load(path)
    if write and current["status"] != "complete":
        validate_graph_state_completion(current, session)
        validate_artifacts(path, current)
    digest = (
        orders_completion.prepare(path, session, current["loop_id"])
        if write and current["status"] != "complete"
        else None
    )

    def update(state: dict[str, Any]) -> dict[str, Any]:
        validate_graph_state_completion(state, session)
        validate_artifacts(path, state)
        if write and state["status"] != "complete":
            if digest is None:
                raise ValueError("order_source_mismatch")
            orders_completion.validate_prepared(path, state, digest)
        proposed = copy.deepcopy(state)
        proposed["status"] = "complete"
        if completed_marker is not None:
            proposed["completed_marker"] = completed_marker
        return proposed

    if (
        write
        and current["status"] == "complete"
        and (completed_marker is None or current.get("completed_marker") == completed_marker)
    ):
        lock = Path(f"{path}.lock")
        attempts = int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5"))
        delay = float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3"))
        if not acquire_dir_lock(lock, attempts, delay)[0]:
            raise ValueError("graph lock or atomic update failed")
        try:
            state = update(load(path))
        finally:
            release_dir_lock(lock)
    else:
        state = transition(path, update, preserve_updated_at=True) if write else update(load(path))
    result: dict[str, Any] = {"session_id": session, "loop_id": state["loop_id"], "status": state["status"]}
    if write:
        result.update(orders_completion.finish(path, session, state["loop_id"]))
    elif current["status"] == "complete":
        orders_completion.status(path, session)
    return result
