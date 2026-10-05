"""Machine-readable agentic-loop graph spec and policy, shared by both providers; materialized byte-for-byte.

`graph-spec.yaml` and `policy.yaml` are JSON-syntax YAML (valid YAML 1.2) read with `json.loads`, so the runtime stays
standard-library only. This module validates them (closed vocabulary, resolving references, acyclic), expands them into
nodes/edges/joins, enforces the spec's edges on a loaded graph (`check`) and builds the `instantiate` state. The pure
core `graph_semantics.py` is untouched: the spec must agree with its label registry, a test asserts it.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any, cast

SPEC_FILE = Path(__file__).with_name("graph-spec.yaml")
POLICY_FILE = Path(__file__).with_name("policy.yaml")
PROFILES = ("units-only", "full")
KINDS = ("node", "join", "guard")
PHASES = ("prep", "freeze", "build", "tail")
INT_KEYS = ("design_doc_min_units", "loop_evals_min_units", "retry_max", "repair_attempts_max")
NODE_FIELDS = frozenset(
    {
        "id",
        "kind",
        "per_unit",
        "profiles",
        "phase",
        "graph_role",
        "label",
        "requires",
        "source",
        "agent_role",
        "prereq_text",
        "ready_when",
        "skip_when",
        "skip_text",
        "retry_max",
    }
)
UNIT_ID = re.compile(r"[1-9][0-9]*")
_CONCRETE = re.compile(r"^(.*)\[([1-9][0-9]*)\]$")
Node = dict[str, Any]


class SpecError(ValueError):
    """A coded spec, policy, enforcement or instantiate refusal; the code is also the trace reason."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the closed code beside the human message and show both in str()."""
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def _cross_unit_dependency(state: dict[str, Any]) -> bool:
    """True when an edge joins two nodes of the same per-unit family (one unit waits on another)."""
    for edge in state["graph"]["edges"]:
        (a, i), (b, j) = split_id(edge["from"]), split_id(edge["to"])
        if i is not None and j is not None and a == b:
            return True
    return False


def _units_lt(state: dict[str, Any], limit: object) -> bool:
    return len(state.get("work_units", {})) < cast(int, limit) and not _cross_unit_dependency(state)


# Judgement predicates are not here on purpose: they stay prose in the node's skip_text.
PREDICATES: dict[str, Callable[[dict[str, Any], object], bool]] = {
    "work_units_lt": _units_lt,
    "work_units_eq0": lambda state, _limit: not state.get("work_units"),
    "always": lambda _state, _limit: True,
    "never": lambda _state, _limit: False,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SpecError("spec_unreadable", f"{path.name}: {error}") from error
    if not isinstance(value, dict):
        raise SpecError("spec_unreadable", f"{path.name} must hold a JSON object")
    return cast(dict[str, Any], value)


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Require exactly the closed policy keys with in-range values."""
    if set(policy) != {*INT_KEYS, "graph"}:
        raise SpecError("policy_keys", f"policy keys must be exactly {sorted({*INT_KEYS, 'graph'})}")
    for key in INT_KEYS:
        value = policy[key]
        if type(value) is not int or not 1 <= value <= (5 if key.endswith("_max") else 1000):
            raise SpecError("policy_value", f"{key} must be an integer in range")
    graph = policy["graph"]
    if not isinstance(graph, dict) or set(cast(dict[str, Any], graph)) != {"profile"}:
        raise SpecError("policy_keys", "graph must hold exactly profile")
    if cast(dict[str, Any], graph)["profile"] not in PROFILES:
        raise SpecError("policy_value", f"graph.profile must be one of {PROFILES}")
    return policy


def load_policy(path: Path | None = None) -> dict[str, Any]:
    """Read and validate policy.yaml (or `path`)."""
    return validate_policy(_read(path or POLICY_FILE))


def split_id(identifier: str) -> tuple[str, str | None]:
    """`U3[2]` -> (`U3`, `2`); an id with no index -> (id, None)."""
    match = _CONCRETE.match(identifier)
    return (match.group(1), match.group(2)) if match else (identifier, None)


def _base(pattern: str) -> str:
    return pattern[:-3] if pattern.endswith("[i]") else pattern


def _requires(node: Node, profile: str) -> list[str]:
    own = node.get("units_only_requires")
    return list(own if profile == "units-only" and own is not None else node["requires"])


def _check_node(node: object) -> Node:
    if not isinstance(node, dict):
        raise SpecError("spec_shape", "every node must be an object")
    item = cast(Node, node)
    if not NODE_FIELDS <= set(item) <= NODE_FIELDS | {"units_only_requires"}:
        raise SpecError("spec_field", f"node {item.get('id')!r} has missing or unknown fields")
    if item["kind"] not in KINDS:
        raise SpecError("spec_kind", f"node {item['id']} kind {item['kind']!r}")
    if item["phase"] not in PHASES:
        raise SpecError("spec_phase", f"node {item['id']} phase {item['phase']!r}")
    profiles = item["profiles"]
    if not isinstance(profiles, list) or not profiles or any(p not in PROFILES for p in cast("list[str]", profiles)):
        raise SpecError("spec_profile", f"node {item['id']} profiles must be a non-empty subset of {PROFILES}")
    per_unit = item["id"].endswith("[i]")
    if item["per_unit"] is not per_unit or ("{i}" in item["label"]) is not per_unit:
        raise SpecError("spec_shape", f"node {item['id']}: per_unit, [i] id and {{i}} label must agree")
    rule = item["skip_when"]
    if rule is not None:
        if not isinstance(rule, dict) or set(cast(dict[str, Any], rule)) != {"predicate", "policy_key"}:
            raise SpecError("spec_predicate", f"node {item['id']} skip_when needs predicate and policy_key")
        rule = cast(dict[str, Any], rule)
        if rule["predicate"] not in PREDICATES:
            raise SpecError("spec_predicate", f"node {item['id']} predicate {rule['predicate']!r} is not registered")
        if (rule["predicate"] == "work_units_lt") is not (rule["policy_key"] in INT_KEYS):
            raise SpecError("spec_policy_key", f"node {item['id']} policy_key {rule['policy_key']!r}")
    retry = item["retry_max"]
    if retry is not None and not (type(retry) is int and 1 <= retry <= 5) and retry not in INT_KEYS:
        raise SpecError("spec_policy_key", f"node {item['id']} retry_max {retry!r}")
    return item


def validate_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Closed vocabulary, unique ids, resolving references and no dependency cycle."""
    if set(spec) != {"spec_version", "unit_join", "unit_root", "nodes"} or spec["spec_version"] != 1:
        raise SpecError("spec_field", "spec needs exactly spec_version 1, unit_join, unit_root and nodes")
    nodes = [_check_node(n) for n in cast(list[Any], spec["nodes"])]
    by_base = {_base(n["id"]): n for n in nodes}
    if len(by_base) != len(nodes):
        raise SpecError("spec_shape", "node ids must be unique")
    graph: dict[str, set[str]] = {}
    for node in nodes:
        for pattern in [*node["requires"], *node.get("units_only_requires", [])]:
            target = by_base.get(_base(pattern))
            if target is None or pattern.endswith("[i]") is not target["per_unit"]:
                raise SpecError("spec_reference", f"node {node['id']} requires unresolved {pattern!r}")
        graph[node["id"]] = {by_base[_base(p)]["id"] for p in node["requires"]}
    join = by_base.get(spec["unit_join"])
    root = by_base.get(_base(spec["unit_root"]))
    if join is None or join["kind"] != "join" or root is None or not root["per_unit"]:
        raise SpecError("spec_reference", "unit_join must name a join and unit_root a per-unit node")
    try:
        tuple(TopologicalSorter(graph).static_order())
    except CycleError as error:
        raise SpecError("spec_cycle", "the spec's requirements contain a cycle") from error
    return spec


def load_spec(path: Path | None = None) -> dict[str, Any]:
    """Read and validate graph-spec.yaml (or `path`) against the current policy."""
    return validate_spec(_read(path or SPEC_FILE))


def spec_sha256(spec: dict[str, Any]) -> str:
    """Stable digest of the parsed spec, independent of file formatting."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def node_for(spec: dict[str, Any], identifier: str) -> Node | None:
    """The spec node a concrete (or bare) id belongs to, or None."""
    wanted = split_id(identifier)[0]
    return next((n for n in spec["nodes"] if _base(n["id"]) == wanted), None)


def before_freeze(spec: dict[str, Any], identifier: str) -> bool:
    """True for preparation and freeze nodes, which author the frozen suite and so run without it."""
    node = node_for(spec, identifier)
    return node is not None and node["phase"] in ("prep", "freeze")


def role_node(spec: dict[str, Any], role: str) -> Node | None:
    """The spec node carrying this graph role (its instruction source and agent role), or None."""
    return next((n for n in spec["nodes"] if n["graph_role"] == role), None)


def unit_root_id(spec: dict[str, Any], unit: str) -> str:
    """The id of a work unit's root node (the node `add-unit` creates and unit dependencies point at)."""
    return str(spec["unit_root"]).replace("[i]", f"[{unit}]")


def skip_when_met(state: dict[str, Any], spec: dict[str, Any], policy: dict[str, Any], identifier: str) -> bool:
    """Evaluate the node's machine skip predicate against the work units and the policy threshold."""
    node = node_for(spec, identifier)
    if node is None or not node["skip_when"]:
        return False
    rule: dict[str, Any] = node["skip_when"]
    return PREDICATES[rule["predicate"]](state, policy.get(rule["policy_key"]))


def fresh_node(node: Node, unit: str | None, policy: dict[str, Any]) -> dict[str, Any]:
    """A pending graph node with the label registry text and the policy's retry bound."""
    retry = node["retry_max"]
    limit = policy["retry_max"] if retry is None else policy[retry] if isinstance(retry, str) else retry
    label = node["label"].replace("{i}", unit or "")
    return {
        "label": label,
        "status": "pending",
        "outcome": "pending",
        "retry": {"attempts": 0, "max": limit},
        "evidence": [],
        "respawn": {"generation": 0, "intent": None},
    }


def _needs(identifier: str, requires: list[str], present: set[str]) -> list[str]:
    """Concrete present ids that satisfy a node's requirement patterns."""
    index = split_id(identifier)[1]
    found: list[str] = []
    for pattern in requires:
        if not pattern.endswith("[i]"):
            found.append(pattern)
        elif index is not None:
            found.append(f"{_base(pattern)}[{index}]")
        else:
            found.extend(sorted(p for p in present if split_id(p)[1] is not None and split_id(p)[0] == _base(pattern)))
    return [item for item in found if item in present]


def required_edges(spec: dict[str, Any], present: set[str]) -> set[tuple[str, str]]:
    """Every (source, target) edge the spec demands among `present` ids; joins take inputs, not edges."""
    edges: set[tuple[str, str]] = set()
    for target in present:
        node = node_for(spec, target)
        if node is not None and node["kind"] == "node":
            edges.update((source, target) for source in _needs(target, node["requires"], present))
    return edges


def expand(spec: dict[str, Any], policy: dict[str, Any], units: list[str], profile: str) -> dict[str, Any]:
    """The nodes, edges and join inputs the spec yields for `units` under `profile` (guards are not graph nodes)."""
    nodes: dict[str, dict[str, Any]] = {}
    for node in spec["nodes"]:
        if node["kind"] == "guard" or profile not in node["profiles"]:
            continue
        indexes: list[str | None] = list(units) if node["per_unit"] else [None]
        for unit in indexes:
            nodes[node["id"].replace("[i]", f"[{unit}]") if unit else node["id"]] = fresh_node(node, unit, policy)
    joins: dict[str, set[str]] = {}
    for node in spec["nodes"]:
        if node["kind"] == "join" and node["id"] in nodes:
            inputs = _needs(node["id"], _requires(node, profile), set(nodes))
            if inputs:
                joins[node["id"]] = set(inputs)
            else:
                del nodes[node["id"]]
    return {"nodes": nodes, "edges": required_edges(spec, set(nodes)), "joins": joins}


def lane(spec: dict[str, Any], policy: dict[str, Any], state: dict[str, Any], unit: str, join: bool) -> dict[str, Any]:
    """What registering `unit` adds: its lane nodes, the spec edges into them and the unit join's new inputs."""
    graph = state["graph"]
    profile = graph.get("spec_profile", "units-only")
    new = {
        identifier: record
        for identifier, record in expand(spec, policy, [unit], profile)["nodes"].items()
        if split_id(identifier)[1] == unit
    }
    edges = sorted((s, t) for s, t in required_edges(spec, set(graph["nodes"]) | set(new)) if t in new)
    join_id = spec["unit_join"]
    join_node = next(n for n in spec["nodes"] if n["id"] == join_id)
    inputs = _needs(join_id, _requires(join_node, profile), set(new)) if join or "spec_sha256" in graph else []
    return {
        "nodes": new,
        "edges": edges,
        "join": {"id": join_id, "node": fresh_node(join_node, None, policy), "inputs": inputs},
    }


def check(state: dict[str, Any]) -> None:
    """Refuse a graph that drifted from the spec: a missing spec edge, and for a stamped graph any node drift."""
    spec, graph = load_spec(), state["graph"]
    nodes = set(graph["nodes"])
    if graph.get("spec_sha256") is not None:
        profile = graph.get("spec_profile")
        if graph["spec_sha256"] != spec_sha256(spec) or profile not in PROFILES:
            raise SpecError("spec_hash_mismatch", "the graph was instantiated from a different spec")
        wanted = set(expand(spec, load_policy(), sorted(state.get("work_units", {})), profile)["nodes"])
        if nodes - wanted:
            raise SpecError("spec_unknown_node", f"nodes not in the spec: {sorted(nodes - wanted)}")
        if wanted - nodes:
            raise SpecError("spec_node_missing", f"spec nodes absent: {sorted(wanted - nodes)}")
    present = {(edge["from"], edge["to"]) for edge in graph["edges"]}
    for source, target in sorted(required_edges(spec, nodes)):
        if (source, target) not in present:
            raise SpecError("spec_edge_missing", f"the spec requires edge {source} -> {target}")


def instantiate(
    state: dict[str, Any], session: str, loop_id: str, profile: str, units: list[str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (proposed state, report): the spec's graph built into an empty loop, or the state itself on a re-run."""
    spec, policy = load_spec(), load_policy()
    digest, graph = spec_sha256(spec), state["graph"]
    report = {"session_id": session, "loop_id": loop_id, "profile": profile}
    if state["session_id"] != session or state["loop_id"] != loop_id:
        raise SpecError("instantiate_refused_foreign", "session or loop does not own this graph")
    if profile not in PROFILES or any(not UNIT_ID.fullmatch(unit) for unit in units):
        raise SpecError(
            "instantiate_refused_bad_id", f"profile must be one of {PROFILES}; units must match [1-9][0-9]*"
        )
    if (
        graph.get("spec_sha256") == digest
        and graph.get("spec_profile") == profile
        and set(units) <= set(state["work_units"])
    ):
        return state, {**report, "status": "noop", "reason_code": "instantiate_noop", "revision": state["revision"]}
    if state["status"] != "in-progress" or graph["active_wave"] is not None:
        raise SpecError("instantiate_refused_state", "instantiate needs an in-progress loop with no active wave")
    if graph["nodes"] or graph["edges"] or graph["joins"] or state["work_units"] or "spec_sha256" in graph:
        raise SpecError("instantiate_refused_nonempty", "the graph is not empty: instantiate builds only from nothing")
    built = expand(spec, policy, units, profile)
    proposed = copy.deepcopy(state)
    proposed["revision"] += 1  # the graph changed: evals frozen at the old revision must go STALE
    proposed["work_units"] = {unit: {"status": "pending"} for unit in units}
    target = proposed["graph"]
    target["nodes"] = built["nodes"]
    target["edges"] = [{"from": s, "to": t} for s, t in sorted(built["edges"])]
    target["joins"] = {
        j: {"id": j, "mode": "all", "inputs": sorted(inputs), "released": False} for j, inputs in built["joins"].items()
    }
    target.update(spec_sha256=digest, spec_profile=profile)
    return proposed, {
        **report,
        "status": "created",
        "reason_code": "instantiate_ok",
        "revision": proposed["revision"],
        "nodes": len(built["nodes"]),
    }
