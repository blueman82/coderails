from __future__ import annotations

import json
import re
import unicodedata
from typing import Any


class GraphError(ValueError):
    """Mark an expected graph validation failure."""


REFERENCE_KEYS = {
    "kind",
    "attempt",
    "wave_id",
    "spawn_call_id",
    "agent_thread_id",
    "task_complete_turn_id",
}
IDENTIFIER_KEYS = {"spawn_call_id", "agent_thread_id", "task_complete_turn_id"}
RESERVED_TOKENS = REFERENCE_KEYS | {"codex_agent"}
_MAX_EVIDENCE_INPUT_UNITS = 1 << 20
_MAX_EVIDENCE_WORK_UNITS = 8 << 20


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _reserved_matches(value: str) -> set[str]:
    candidate = _normalized(value).casefold()
    return {candidate} if candidate in RESERVED_TOKENS else set()


def classify_worker_evidence(
    value: object,
    known_identifiers: set[str] | frozenset[str] = frozenset(),
) -> tuple[bool, set[str]]:
    """Return a worker-shaped boolean and normalized identifier set for nested data."""
    normalized_identifiers = {_normalized(identifier) for identifier in known_identifiers}
    stack = [(value, True, False)]
    seen_containers: dict[int, object] = {}
    input_units = work_units = 0
    shaped = False
    identifiers: set[str] = set()
    while stack:
        item, is_input, is_identifier = stack.pop()
        if isinstance(item, str):
            units = len(item)
        elif item is None:
            units = 4
        elif isinstance(item, bool):
            units = 5
        elif isinstance(item, (int, float)):
            try:
                units = len(str(item))
            except ValueError as error:
                raise GraphError("worker evidence exceeds classifier limits") from error
        else:
            units = 1
        input_units += units if is_input else 0
        work_units += units
        if input_units > _MAX_EVIDENCE_INPUT_UNITS or work_units > _MAX_EVIDENCE_WORK_UNITS:
            raise GraphError("worker evidence exceeds classifier limits")
        if isinstance(item, str):
            normalized = _normalized(item)
            if normalized in normalized_identifiers:
                shaped = True
                identifiers.add(normalized)
            if is_identifier and normalized:
                identifiers.add(normalized)
            try:
                decoded = json.loads(normalized)
            except json.JSONDecodeError:
                matches = _reserved_matches(normalized)
                shaped = shaped or bool(matches)
            except RecursionError as error:
                raise GraphError("worker evidence exceeds classifier limits") from error
            else:
                stack.append((decoded, False, is_identifier))
            continue
        if not isinstance(item, (dict, list)):
            continue
        identity = id(item)
        if identity in seen_containers:
            raise GraphError("worker evidence contains a repeated container")
        seen_containers[identity] = item
        if isinstance(item, list):
            stack.extend((nested, is_input, is_identifier) for nested in item)
            continue
        for raw_key, nested in item.items():
            matches = _reserved_matches(raw_key) if isinstance(raw_key, str) else set()
            stack.extend(((raw_key, is_input, False),
                          (nested, is_input, bool(matches & IDENTIFIER_KEYS))))
    return shaped, identifiers


def task_name(node_id: str, attempt: int = 1) -> str:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise GraphError("graph worker attempt must be a positive integer")
    suffix = "" if attempt == 1 else f"_a{attempt}"
    return f"loop_worker_{node_id.encode().hex()}{suffix}"


def task_node(name: str) -> str:
    match = re.fullmatch(r"loop_worker_([0-9a-f]+)(?:_a([2-9][0-9]*))?", name)
    if match is None:
        raise GraphError("graph worker task name must use the native lowercase format")
    encoded, retry = match.groups()
    attempt = int(retry) if retry else 1
    if len(encoded) % 2:
        raise GraphError("graph worker task name is not reversible")
    try:
        node_id = bytes.fromhex(encoded).decode()
    except (UnicodeDecodeError, ValueError) as error:
        raise GraphError("graph worker task name is not reversible") from error
    if not node_id or task_name(node_id, attempt) != name:
        raise GraphError("graph worker task name is not canonical")
    return node_id


def is_frozen_loop_evals(evals: dict[str, Any]) -> bool:
    """Return whether an ungraded loop suite is safe to authorize dispatch."""
    level = evals.get("verification_level")
    frozen_sha = evals.get("frozen_sha")
    raw_evals = evals.get("evals")
    if (
        isinstance(level, bool)
        or not isinstance(level, (int, float))
        or level < 1
        or not isinstance(frozen_sha, str)
        or not frozen_sha.strip()
        or evals.get("result") is not None
        or evals.get("grading") is not None
        or not isinstance(raw_evals, list)
        or not any(isinstance(item, dict) and item.get("priority") == "P0" for item in raw_evals)
    ):
        return False
    for item in raw_evals:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            return False
        mode = item.get("mode")
        if mode not in {"scripted", "agent-run"}:
            return False
        if mode == "scripted" and not all(
            isinstance(item.get(field), str) and item[field].strip()
            for field in ("cmd", "negative_control")
        ):
            return False
    return True


def active_nodes(active_wave: Any, nodes: dict[str, Any], revision: int) -> set[str]:
    if active_wave is None:
        return set()
    if not isinstance(active_wave, dict):
        raise GraphError("graph.active_wave must be an object")
    if active_wave.get("id") != f"wave-{revision}" or active_wave.get("revision") != revision:
        raise GraphError("graph.active_wave identity must match the root revision")
    wave_nodes = active_wave.get("nodes")
    if (
        not isinstance(wave_nodes, list)
        or not wave_nodes
        or any(not isinstance(item, str) for item in wave_nodes)
        or len(wave_nodes) != len(set(wave_nodes))
    ):
        raise GraphError("graph.active_wave.nodes must be a non-empty unique array")
    if any(node_id not in nodes or nodes[node_id]["status"] != "running" for node_id in wave_nodes):
        raise GraphError("graph.active_wave must contain known running nodes")
    return set(wave_nodes)
