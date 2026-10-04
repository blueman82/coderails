"""Validate stable native graph identifiers and worker evidence shape."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Union, cast


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
# A failed attempt whose spawn_agent call was refused has a call but no child thread or completion.
REFUSED_KEYS = {"kind", "attempt", "wave_id", "spawn_call_id", "outcome"}
REFUSED_OUTCOME = "launch_refused"
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
                reserved_matches = _reserved_matches(normalized)
                shaped = shaped or bool(reserved_matches)
            except RecursionError as error:
                raise GraphError("worker evidence exceeds classifier limits") from error
            else:
                stack.append((cast(object, decoded), False, is_identifier))
            continue
        if not isinstance(item, (dict, list)):
            continue
        item = cast(Union[dict[object, object], list[object]], item)
        identity = id(item)
        if identity in seen_containers:
            raise GraphError("worker evidence contains a repeated container")
        seen_containers[identity] = item
        if isinstance(item, list):
            stack.extend((nested, is_input, is_identifier) for nested in item)
            continue
        for raw_key, nested in item.items():
            key_matches: set[str] = _reserved_matches(raw_key) if isinstance(raw_key, str) else set()
            stack.extend(((raw_key, is_input, False), (nested, is_input, bool(key_matches & IDENTIFIER_KEYS))))
    return shaped, identifiers


def next_attempt(node: dict[str, Any]) -> int:
    """Allocate a unique native dispatch attempt across retries and stale respawns."""
    return int(node["retry"]["attempts"]) + int(node["respawn"]["generation"]) + 1


def _task_suffix(attempt: object) -> str:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise GraphError("graph worker attempt must be a positive integer")
    return "" if attempt == 1 else f"_a{attempt}"


def task_name(loop_id: str, node_id: str, attempt: object = 1) -> str:
    """Return the canonical worker task name for one loop and node attempt."""
    if not isinstance(cast(object, loop_id), str) or not loop_id:
        raise GraphError("graph worker loop identity must be nonempty")
    if not isinstance(cast(object, node_id), str) or not node_id:
        raise GraphError("graph worker node identity must be nonempty")
    suffix = _task_suffix(attempt)
    return f"loop_worker_{loop_id.encode().hex()}_{node_id.encode().hex()}{suffix}"


def is_legacy_task_name(name: str) -> bool:
    """Return whether a name has the retired node-only shape; such names are refused, never decoded."""
    return re.fullmatch(r"loop_worker_[0-9a-f]+(?:_a[1-9][0-9]*)?", name) is not None


def task_node(name: str) -> tuple[str, str]:
    """Decode a loop-scoped task name into (loop_id, node_id); anything else, node-only names included, raises."""
    match = re.fullmatch(r"loop_worker_([0-9a-f]+)_([0-9a-f]+)(?:_a([1-9][0-9]*))?", name)
    if match is None:
        raise GraphError("graph worker task name must use the native lowercase format")
    encoded_loop, encoded_node, retry = match.groups()
    attempt = int(retry) if retry else 1
    if len(encoded_loop) % 2 or len(encoded_node) % 2:
        raise GraphError("graph worker task name is not reversible")
    try:
        loop_id = bytes.fromhex(encoded_loop).decode()
        node_id = bytes.fromhex(encoded_node).decode()
    except (UnicodeDecodeError, ValueError) as error:
        raise GraphError("graph worker task name is not reversible") from error
    if not loop_id or not node_id or task_name(loop_id, node_id, attempt) != name:
        raise GraphError("graph worker task name is not canonical")
    return loop_id, node_id


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
    ):
        return False
    has_p0 = False
    for raw_item in cast(list[object], raw_evals):
        item = raw_item
        if not isinstance(item, dict):
            return False
        item = cast(dict[str, Any], item)
        has_p0 = has_p0 or item.get("priority") == "P0"
        if not isinstance(item.get("id"), str) or not item["id"].strip():
            return False
        mode = item.get("mode")
        if mode not in {"scripted", "agent-run"}:
            return False
        if mode == "scripted" and not all(
            isinstance(item.get(field), str) and item[field].strip() for field in ("cmd", "negative_control")
        ):
            return False
    return has_p0
