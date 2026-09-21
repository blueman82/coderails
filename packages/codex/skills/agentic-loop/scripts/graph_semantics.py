#!/usr/bin/env python3
"""Pure schema-v3 validation and transitions for provider graph state."""

from __future__ import annotations

import copy
import re
from collections import deque
from typing import Any, NoReturn, cast

STATUSES = frozenset({"pending", "ready", "running", "blocked", "done", "skipped", "failed", "hard-stop", "stale"})
SUCCESS = frozenset({"done", "skipped"})
PERSISTED_STATUSES = STATUSES - {"failed"}
ID_PATTERNS = (
    r"S-(?:2|1)",
    r"S0(?:\.[45])?",
    r"S1",
    r"S2(?:\.[5678][a-e]?)?",
    r"J2(?:\.8)?",
    r"U(?:3|4|4b-review|5|5-repair|6|7/8|4b-merge-gate|10-respawn)\[[1-9][0-9]*\]",
    r"J12-all-units",
    r"G1[0-2]",
    r"S9-(?:wiki|docs)",
    r"S13-(?:proof|retro|complete)",
)
STABLE_ID = re.compile("(?:" + "|".join(ID_PATTERNS) + ")$")
LABELS = {
    "S-2": "Initialize loop state",
    "S-1": "Improve prompt",
    "S0": "Read authorization envelope",
    "S0.4": "Record model cost",
    "S0.5": "Apply operating rules",
    "S1": "Plan work",
    "S2": "Run preflight",
    "S2.5": "Resolve design fork",
    "S2.6": "Choose disposition",
    "J2": "Preflight decisions joined",
    "S2.7a": "Write specification",
    "S2.7b": "Write implementation plan",
    "S2.7c": "Freeze loop evals",
    "S2.7e": "Freeze proof plan",
    "S2.8": "Assign model roles",
    "J2.8": "Implementation ready",
    "J12-all-units": "All units joined",
    "G10": "Guard replacement worker",
    "G11": "Check confidence labels",
    "G12": "Fresh artifact check",
    "S9-wiki": "Update wiki",
    "S9-docs": "Sync docs",
    "S13-proof": "Run frozen proofs",
    "S13-retro": "Write loop retrospective",
    "S13-complete": "Complete loop",
}


class GraphSemanticError(ValueError):
    """A deterministic semantic validation error."""

    def __init__(self, code: str, message: str) -> None:
        """Initialize the stable error code and message."""
        super().__init__(message)
        self.code = code
        self.message = message


def _error(code: str, message: str) -> NoReturn:
    raise GraphSemanticError(code, message)


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error("shape", f"{label} must be an object")
    return cast(dict[str, Any], value)


def _array(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        _error("shape", f"{label} must be an array")
    return cast(list[Any], cast(object, value))


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _error("shape", f"{label} must be a non-empty string")
    return value


def _integer(value: object, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        _error("shape", f"{label} must be an integer at least {minimum}")
    return value


def _label_for(node_id: str) -> str:
    if node_id in LABELS:
        return LABELS[node_id]
    match = re.fullmatch(r"S2\.7d\[([1-9][0-9]*)\]", node_id)
    if match:
        return f"Freeze unit {match.group(1)} evaluation"
    match = re.fullmatch(r"U(3|4|4b-review|5|5-repair|6|7/8|4b-merge-gate|10-respawn)\[([1-9][0-9]*)\]", node_id)
    if match is None:
        _error("node_id", f"node id {node_id} is not a stable schema-v3 id")
    action = {
        "3": "Build unit",
        "4": "Verify unit artifact",
        "4b-review": "Review unit",
        "5": "Diagnose unit",
        "5-repair": "Repair unit",
        "6": "Resolve continuation",
        "7/8": "Push or deploy unit",
        "4b-merge-gate": "Merge gate unit",
        "10-respawn": "Respawn unit",
    }[match.group(1)]
    return f"{action} {match.group(2)}"


def _validate_node(node_id: str, value: object) -> dict[str, Any]:
    if not STABLE_ID.fullmatch(node_id):
        _error("node_id", f"node id {node_id} is not a stable schema-v3 id")
    node = _object(value, f"node {node_id}")
    if node.get("label") != _label_for(node_id):
        _error("node_label", f"node {node_id} label must match the registry")
    status = node.get("status")
    if status not in PERSISTED_STATUSES:
        message = f"node {node_id} cannot persist failed status"
        if status != "failed":
            message = f"node {node_id} has invalid status"
        _error("node_status", message)
    if node.get("outcome") != status:
        _error("node_outcome", f"node {node_id} status and outcome disagree")
    retry = _object(node.get("retry"), f"node {node_id}.retry")
    attempts = _integer(retry.get("attempts"), f"node {node_id} retry.attempts")
    maximum = _integer(retry.get("max"), f"node {node_id} retry.max", 1)
    if maximum > 5 or attempts > maximum:
        _error("retry", f"node {node_id} has invalid retry bounds")
    if not isinstance(node.get("evidence"), list):
        _error("evidence", f"node {node_id}.evidence must be an array")
    respawn = _object(node.get("respawn"), f"node {node_id}.respawn")
    generation = _integer(respawn.get("generation"), f"node {node_id} respawn.generation")
    intent = respawn.get("intent")
    if intent is not None:
        intent_object = _object(intent, f"node {node_id} respawn.intent")
        invalid_intent = intent_object.get("generation") != generation
        invalid_intent |= not isinstance(intent_object.get("reason"), str)
        invalid_intent |= not str(intent_object.get("reason", "")).strip()
        if invalid_intent:
            _error("respawn", f"node {node_id} has invalid respawn intent")
    if status == "stale":
        _stale_check(node.get("stale_check"), f"node {node_id}")
    return node


def _stale_check(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _error("stale_check", f"{label} stale_check must confirm a completed check")
    check = cast(dict[str, Any], value)
    valid = check.get("checked") is True
    valid &= isinstance(check.get("method"), str) and bool(str(check.get("method", "")).strip())
    valid &= isinstance(check.get("result"), str) and bool(str(check.get("result", "")).strip())
    if not valid:
        _error("stale_check", f"{label} stale_check must confirm a completed check")
    return check


def _dependencies(graph: dict[str, Any]) -> dict[str, set[str]]:
    nodes = graph["nodes"]
    dependencies: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for index, raw_edge in enumerate(graph["edges"]):
        edge = _object(raw_edge, f"edge {index}")
        source = _text(edge.get("from"), f"edge {index}.from")
        target = _text(edge.get("to"), f"edge {index}.to")
        if source not in nodes or target not in nodes or source == target:
            _error("edge", f"edge {index} references an unknown or identical node")
        dependencies[target].add(source)
    for join_id, raw_join in graph["joins"].items():
        if join_id not in nodes:
            _error("join", f"join {join_id} references an unknown node")
        join = _object(raw_join, f"join {join_id}")
        if join.get("id") != join_id:
            _error("join_id", f"join {join_id} id must equal its key")
        if join.get("mode") != "all" or not isinstance(join.get("released"), bool):
            _error("join", f"join {join_id} must be an all-input join")
        inputs = _array(join.get("inputs"), f"join {join_id}.inputs")
        if not inputs or any(not isinstance(item, str) for item in inputs) or len(inputs) != len(set(inputs)):
            _error("join", f"join {join_id}.inputs must be a non-empty unique array")
        if any(item not in nodes or item == join_id for item in inputs):
            _error("join", f"join {join_id} references an unknown or identical input")
        dependencies[join_id].update(inputs)
        if join["released"] != (nodes[join_id]["status"] == "done"):
            _error("join", f"join {join_id} release state disagrees with its node")
        if join["released"] and not all(nodes[item]["status"] in SUCCESS for item in inputs):
            _error("join", f"join {join_id} released before every input succeeded")
    return dependencies


def _validate_cycle(dependencies: dict[str, set[str]]) -> None:
    outgoing: dict[str, set[str]] = {node_id: set() for node_id in dependencies}
    indegree = {node_id: len(inputs) for node_id, inputs in dependencies.items()}
    for target, inputs in dependencies.items():
        for source in inputs:
            outgoing[source].add(target)
    queue: deque[str] = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    seen = 0
    while queue:
        source = queue.popleft()
        seen += 1
        for target in sorted(outgoing[source]):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if seen != len(dependencies):
        _error("cycle", "graph contains a dependency cycle")


def _validate_active_wave(graph: dict[str, Any], revision: int) -> None:
    active = graph.get("active_wave")
    running = {node_id for node_id, node in graph["nodes"].items() if node["status"] == "running"}
    if active is None:
        if running:
            _error("active_wave", "running nodes must exactly match the active wave")
        return
    wave = _object(active, "active_wave")
    wave_id = wave.get("wave_id")
    if not isinstance(wave_id, str) or not re.fullmatch(r"wave-[1-9][0-9]*", wave_id):
        _error("active_wave", "active_wave.wave_id must be a wave identifier")
    if wave.get("revision") != revision:
        _error("active_wave", "active_wave revision must equal state revision")
    nodes = _array(wave.get("nodes"), "active_wave.nodes")
    if not nodes or any(not isinstance(node_id, str) for node_id in nodes) or len(nodes) != len(set(nodes)):
        _error("active_wave", "active_wave.nodes must be a non-empty unique array")
    if set(nodes) != running:
        _error("active_wave", "running nodes must exactly match the active wave")


def validate(state: object) -> dict[str, Any]:
    """Validate a complete schema-v3 state without mutating it."""
    root = _object(state, "state")
    if root.get("schema_version") != 3:
        _error("schema_version", "schema_version must be 3")
    revision = _integer(root.get("revision"), "revision", 1)
    graph = _object(root.get("graph"), "graph")
    nodes = _object(graph.get("nodes"), "graph.nodes")
    for node_id, node in nodes.items():
        _validate_node(node_id, node)
    _array(graph.get("edges"), "graph.edges")
    _object(graph.get("joins"), "graph.joins")
    if "active_wave" not in graph or "hard_stop" not in graph:
        _error("graph", "graph must declare active_wave and hard_stop")
    if graph["hard_stop"] is not None and not isinstance(graph["hard_stop"], dict):
        _error("hard_stop", "graph.hard_stop must be null or an object")
    dependencies = _dependencies(graph)
    _validate_cycle(dependencies)
    _validate_active_wave(graph, revision)
    return root


def _release_joins(state: dict[str, Any]) -> list[str]:
    graph = state["graph"]
    released: list[str] = []
    for join_id in sorted(graph["joins"]):
        join = graph["joins"][join_id]
        if not join["released"] and all(graph["nodes"][node_id]["status"] in SUCCESS for node_id in join["inputs"]):
            join["released"] = True
            graph["nodes"][join_id]["status"] = "done"
            graph["nodes"][join_id]["outcome"] = "done"
            released.append(join_id)
    return released


def ready(state: object) -> list[str]:
    """Return ready non-join nodes in stable ID order."""
    root = validate(state)
    graph = root["graph"]
    if graph["active_wave"] is not None or graph["hard_stop"] is not None:
        return []
    dependencies = _dependencies(graph)
    return sorted(
        node_id
        for node_id, node in graph["nodes"].items()
        if node_id not in graph["joins"]
        and node["status"] == "pending"
        and all(graph["nodes"][source]["status"] in SUCCESS for source in dependencies[node_id])
    )


def begin_wave(state: object) -> dict[str, Any]:
    """Propose one wave containing every currently ready node."""
    root = copy.deepcopy(validate(state))
    graph = root["graph"]
    if graph["active_wave"] is not None:
        _error("active_wave", "an active wave already exists")
    if graph["hard_stop"] is not None:
        _error("hard_stop", "the graph is hard-stopped")
    _release_joins(root)
    nodes = ready(root)
    if not nodes:
        _error("ready", "no graph nodes are ready")
    root["revision"] += 1
    for node_id in nodes:
        graph["nodes"][node_id]["status"] = "running"
        graph["nodes"][node_id]["outcome"] = "running"
    wave = {"wave_id": f"wave-{root['revision']}", "revision": root["revision"], "nodes": nodes}
    graph["active_wave"] = wave
    return {"state": root, "wave": copy.deepcopy(wave)}


def _result(value: object, node_id: str) -> dict[str, Any]:
    result = _object(value, f"result {node_id}")
    outcome = _text(result.get("outcome"), f"result {node_id}.outcome")
    if outcome not in {"done", "skipped", "failed", "stale"}:
        _error("result", f"result {node_id} has invalid outcome")
    _text(result.get("evidence"), f"result {node_id}.evidence")
    if outcome == "stale":
        _stale_check(result.get("stale_check"), f"result {node_id}")
    keys: set[str] = {"outcome", "evidence"}
    if outcome == "stale":
        keys.add("stale_check")
    if set(result) != keys:
        _error("result", f"result {node_id} has invalid fields")
    return result


def record_wave(state: object, wave_id: object, results: object) -> dict[str, Any]:
    """Propose an exact active-wave result transition."""
    root = validate(state)
    graph = root["graph"]
    active = graph["active_wave"]
    if active is None:
        _error("active_wave", "no active wave exists")
    active = cast(dict[str, Any], active)
    if wave_id != active["wave_id"]:
        _error("wave_id", "result wave id does not match the active wave")
    result_map = _object(results, "results")
    if set(result_map) != set(active["nodes"]):
        _error("result_set", "result keys must exactly match the active wave")
    parsed = {node_id: _result(value, node_id) for node_id, value in result_map.items()}
    proposed = copy.deepcopy(root)
    proposed_graph = proposed["graph"]
    for node_id in sorted(parsed):
        result = parsed[node_id]
        node = proposed_graph["nodes"][node_id]
        node["evidence"].append(result["evidence"])
        outcome = result["outcome"]
        if outcome in SUCCESS:
            node["status"] = outcome
            node["outcome"] = outcome
        elif outcome == "stale":
            node["status"] = "stale"
            node["outcome"] = "stale"
            node["stale_check"] = result["stale_check"]
        else:
            node["retry"]["attempts"] += 1
            exhausted = node["retry"]["attempts"] >= node["retry"]["max"]
            node["status"] = "hard-stop" if exhausted else "pending"
            node["outcome"] = node["status"]
            if exhausted:
                proposed_graph["hard_stop"] = {"node": node_id, "reason": "retry exhaustion"}
    proposed_graph["active_wave"] = None
    released = _release_joins(proposed)
    proposed["revision"] += 1
    return {"state": proposed, "released_joins": released, "ready": ready(proposed)}


def respawn_stale(state: object, node_id: object, reason: object) -> dict[str, Any]:
    """Request a later provider-native respawn for one stale node."""
    root = copy.deepcopy(validate(state))
    graph = root["graph"]
    if graph["active_wave"] is not None:
        _error("active_wave", "cannot respawn while a wave is active")
    node_key = _text(node_id, "node_id")
    reason_text = _text(reason, "reason")
    if node_key not in graph["nodes"] or graph["nodes"][node_key]["status"] != "stale":
        _error("respawn", "respawn requires a stale node")
    node = graph["nodes"][node_key]
    _stale_check(node.get("stale_check"), f"node {node_key}")
    node["respawn"]["generation"] += 1
    generation = node["respawn"]["generation"]
    node["respawn"]["intent"] = {"generation": generation, "reason": reason_text}
    node["status"] = "pending"
    node["outcome"] = "pending"
    root["revision"] += 1
    return {"state": root, "respawn": {"node_id": node_key, "generation": generation, "reason": reason_text}}


def hard_stop(state: object, node_id: object, reason: object) -> dict[str, Any]:
    """Propose an explicit terminal stop without changing topology."""
    root = copy.deepcopy(validate(state))
    graph = root["graph"]
    node_key = _text(node_id, "node_id")
    reason_text = _text(reason, "reason")
    if node_key not in graph["nodes"] or graph["nodes"][node_key]["status"] in SUCCESS:
        _error("hard_stop", "hard_stop requires an unfinished node")
    node = graph["nodes"][node_key]
    node["status"] = "hard-stop"
    node["outcome"] = "hard-stop"
    graph["hard_stop"] = {"node": node_key, "reason": reason_text}
    active = graph["active_wave"]
    if active is not None and node_key in active["nodes"]:
        active["nodes"] = [item for item in active["nodes"] if item != node_key]
        if active["nodes"]:
            active["revision"] = root["revision"] + 1
        else:
            graph["active_wave"] = None
    root["revision"] += 1
    return {"state": root, "hard_stop": copy.deepcopy(graph["hard_stop"])}


def inspect(state: object) -> dict[str, Any]:
    """Return canonical graph state without provider-owned dispatch data."""
    root = validate(state)
    graph = root["graph"]
    return {
        "revision": root["revision"],
        "active_wave": copy.deepcopy(graph["active_wave"]),
        "running": sorted(node_id for node_id, node in graph["nodes"].items() if node["status"] == "running"),
        "ready": ready(root),
        "hard_stop": copy.deepcopy(graph["hard_stop"]),
    }


def can_complete(state: object) -> dict[str, Any]:
    """Return canonical completion eligibility, excluding provider work-unit gates."""
    root = validate(state)
    graph = root["graph"]
    blockers: list[str] = []
    if graph["active_wave"] is not None:
        blockers.append("active_wave")
    if graph["hard_stop"] is not None:
        blockers.append("hard_stop")
    unfinished = sorted(node_id for node_id, node in graph["nodes"].items() if node["status"] not in SUCCESS)
    if unfinished:
        blockers.append("unfinished:" + ",".join(unfinished))
    unreleased = sorted(join_id for join_id, join in graph["joins"].items() if not join["released"])
    if unreleased:
        blockers.append("unreleased:" + ",".join(unreleased))
    return {"eligible": not blockers, "blockers": blockers}
