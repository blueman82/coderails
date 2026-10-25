"""Canonical labels and display names for schema-v3 graph nodes."""

from __future__ import annotations

import re
from collections.abc import Callable

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
NODE_NAMES = {
    "S-2": "Initializer",
    "S-1": "Editor",
    "S0": "Authorizer",
    "S0.4": "Accountant",
    "S0.5": "Steward",
    "S1": "Planner",
    "S2": "Scout",
    "S2.5": "Designer",
    "S2.6": "Decider",
    "J2": "Joiner",
    "S2.7a": "Specifier",
    "S2.7b": "Planner",
    "S2.7c": "Grader",
    "S2.7e": "Prover",
    "S2.8": "Router",
    "J2.8": "Gatekeeper",
    "J12-all-units": "Joiner",
    "G10": "Guardian",
    "G11": "Linter",
    "G12": "Verifier",
    "S9-wiki": "Archivist",
    "S9-docs": "Editor",
    "S13-proof": "Prover",
    "S13-retro": "Reporter",
    "S13-complete": "Closer",
}
ACTION_NAMES = {
    "3": "Builder",
    "4": "Verifier",
    "4b-review": "Reviewer",
    "5": "Investigator",
    "5-repair": "Repairer",
    "6": "Resolver",
    "7/8": "Publisher",
    "4b-merge-gate": "Gatekeeper",
    "10-respawn": "Respawner",
}
UNIT_LANES = {
    **{unit: f"A-{unit}" for unit in range(1, 7)},
    **{unit: f"B-{unit - 6}" for unit in range(7, 13)},
    **{unit: f"C-{unit - 12}" for unit in range(13, 19)},
    **{unit: f"D-{unit - 18}" for unit in range(19, 25)},
    25: "I-1",
    26: "F-1",
    27: "F-2",
    28: "L-1",
    29: "G-1",
    30: "R-1",
    31: "O-1",
    32: "V-1",
    33: "H-1",
}
UNIT_ID = re.compile(r"(?:S2\.7d|U(?:3|4|4b-review|5|5-repair|6|7/8|4b-merge-gate|10-respawn))\[([1-9][0-9]*)\]")
ACTION_ID = re.compile(r"U(3|4|4b-review|5|5-repair|6|7/8|4b-merge-gate|10-respawn)\[[1-9][0-9]*\]")
FREEZER_ID = re.compile(r"S2\.7d\[[1-9][0-9]*\]")


def describe_node(node_id: str, validate: Callable[[str], str]) -> dict[str, str | None]:
    """Return a display name, optional lane code, and the unchanged node ID.

    Args:
        node_id: Stable node identifier from the validated graph.
        validate: The graph semantics registry validator for schema-v3 IDs.

    Returns:
        A presentation record keyed by the original stable identifier.
    """
    validate(node_id)
    unit = UNIT_ID.fullmatch(node_id)
    action = ACTION_ID.fullmatch(node_id)
    name = NODE_NAMES.get(node_id)
    if name is None and FREEZER_ID.fullmatch(node_id):
        name = "Freezer"
    if name is None and action is not None:
        name = ACTION_NAMES[action.group(1)]
    if name is None:
        raise ValueError(f"registered node {node_id!r} has no display name")
    lane = UNIT_LANES.get(int(unit.group(1))) if unit else None
    display = f"{name} · {lane} [{node_id}]" if lane else f"{name} [{node_id}]"
    return {"job_name": name, "lane_code": lane, "display": display}


def node_names(nodes: dict[str, object], validate: Callable[[str], str]) -> dict[str, dict[str, str | None]]:
    """Return display records for every node, keyed by its stable graph ID.

    Args:
        nodes: Mapping of registered graph node IDs to node records.
        validate: The graph semantics registry validator for schema-v3 IDs.

    Returns:
        Display records in stable ID order.
    """
    return {node_id: describe_node(node_id, validate) for node_id in sorted(nodes)}
