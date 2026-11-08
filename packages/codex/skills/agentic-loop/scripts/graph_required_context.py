"""Required dispatch skills and checks from registered graph and unit facts."""

from __future__ import annotations

import re
from typing import Any, cast

import graph_spec

CHECKS = ("dispatch-contract", "frozen-evals", "source-binding", "publication", "lessons")


def validate_context(context: object) -> None:
    """Refuse malformed required context before a dispatch record is trusted."""
    if not isinstance(context, dict):
        raise ValueError("contract required_context needs skills and checks")
    values = cast(dict[str, object], context)
    if set(values) != {"skills", "checks"}:
        raise ValueError("contract required_context needs skills and checks")
    for key in ("skills", "checks"):
        items = values[key]
        if not isinstance(items, list):
            raise ValueError(f"contract required_context {key} must be an array of strings")
        objects = cast(list[object], items)
        if not all(isinstance(item, str) for item in objects):
            raise ValueError(f"contract required_context {key} must be an array of strings")
        strings = cast(list[str], items)
        if len(strings) != len(set(strings)):
            raise ValueError(f"contract required_context {key} contains duplicates")
    skills = cast(list[str], values["skills"])
    checks = cast(list[str], values["checks"])
    if any(re.fullmatch(r"[a-z][a-z0-9-]*", skill) is None for skill in skills):
        raise ValueError("contract required_context has an invalid skill")
    if any(check not in CHECKS for check in checks):
        raise ValueError("contract required_context has an unknown check")


def required_context(state: dict[str, Any], node_id: str) -> dict[str, list[str]]:
    """Derive mandatory skill routes and checks from registered graph and unit facts."""
    node = graph_spec.node_for(graph_spec.load_spec(), node_id)
    if node is None:
        raise ValueError(f"node {node_id} is absent from the graph specification")
    skills = ["agentic-loop"]
    source = node.get("source")
    if isinstance(source, str) and source.startswith("skills/") and source.endswith("/SKILL.md"):
        skill = source.split("/")[1]
        if skill not in skills:
            skills.append(skill)
    unit_id = graph_spec.split_id(node_id)[1]
    raw_units = state.get("work_units", {})
    units = cast(dict[str, object], raw_units) if isinstance(raw_units, dict) else {}
    found: object = units.get(unit_id, {}) if unit_id else {}
    unit = cast(dict[str, Any], found) if isinstance(found, dict) else {}
    checks = ["dispatch-contract"]
    if node.get("phase") == "build":
        checks.append("frozen-evals")
    if unit.get("manifest") or unit.get("worktree"):
        checks.append("source-binding")
    if node.get("agent_role") == "loop-worker":
        checks.append("publication")
    if unit.get("manifest") or unit.get("worktree") or unit.get("lessons"):
        checks.append("lessons")
    return {"skills": skills, "checks": checks}
