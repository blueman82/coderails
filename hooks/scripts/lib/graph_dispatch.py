"""Own Claude graph dispatch envelopes and atomic native-evidence transitions."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from .graph_evidence import ENVELOPE_KEY, cursor, envelope, object_value, transcript
from .graph_evidence_bind import bind_wave
from .graph_evidence_revalidate import revalidate_all
from .graph_executor import ROOT, graph_semantics, load, transition, validate_state
from .loop_completion import validate_completion
from .loop_evals import read_loop_evals_result
from .loop_state_common import LoopState, read_state

TARGETS = {
    "S-1": "skills/improve-prompt/SKILL.md",
    "S2": "agents/preflight-scout.md",
    "S2.5": "agents/design-scout.md",
    "S2.6": "agents/disposition-scout.md",
    "S2.7a": "agents/spec-reviewer.md",
    "S2.7c": "skills/task-evals/SKILL.md",
    "S2.7e": "agents/proof-author.md",
    "G12": "skills/verify-merged-pr/SKILL.md",
    "S9-wiki": "agents/wiki-writer.md",
    "S9-docs": "agents/docs-auditor.md",
    "U3": "agents/loop-worker.md",
    "U6": "commands/push.md",
}


def before_freeze(node_id: str) -> bool:
    """Recognize only documented preparation nodes that author the frozen suite."""
    return bool(re.match(r"^(S-|S0|S1(?:$|[^0-9])|S2(?:$|[^0-9])|J2(?:$|[^0-9]))", node_id))


def validate_dispatch_evals(path: Path, state: dict[str, Any], node_id: str, worker: bool = False) -> None:
    """Require session-bound frozen eval authority for implementation dispatch."""
    if before_freeze(node_id) and not worker:
        return
    units = state.get("work_units", {})
    if not isinstance(units, dict):
        raise ValueError("work_units must be a current-schema object")
    if not units:
        return
    suite = read_state(path.with_name("evals.json"))
    if any(suite.get(key) != state[key] for key in ("session_id", "loop_id")):
        raise ValueError("frozen eval suite belongs to another session or loop")
    verdict = read_loop_evals_result(path.parent)
    if verdict not in {"GO", "VERIFICATION_LEVEL0", "FROZEN"}:
        raise ValueError(f"dispatch requires frozen loop evals before build; current verdict: {verdict}")


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
    for node_id in nodes:
        role = state["graph"]["nodes"][node_id].get("graph_role") or re.sub(r"\[.*\]$", "", node_id)
        source = TARGETS.get(role)
        item: dict[str, Any] = {
            "node_id": node_id,
            "graph_role": role,
            "path": source,
            "unresolved": not source or not (ROOT / source).is_file(),
        }
        if state["graph"]["active_wave"]:
            item["prompt_prefix"] = ENVELOPE_KEY + "=" + json.dumps(ownership(state, node_id), sort_keys=True)
        result.append(item)
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
        or read_loop_evals_result(path.parent) != "GO"
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
