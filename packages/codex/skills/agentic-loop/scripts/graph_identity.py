from __future__ import annotations

import re
from typing import Any


class IdentityError(ValueError):
    pass


def task_name(node_id: str, attempt: int = 1) -> str:
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise IdentityError("graph worker attempt must be a positive integer")
    suffix = "" if attempt == 1 else f"_a{attempt}"
    return f"loop_worker_{node_id.encode().hex()}{suffix}"


def task_node(name: str) -> str:
    match = re.fullmatch(r"loop_worker_([0-9a-f]+)(?:_a([2-9][0-9]*))?", name)
    if match is None:
        raise IdentityError("graph worker task name must use the native lowercase format")
    encoded, retry = match.groups()
    attempt = int(retry) if retry else 1
    if len(encoded) % 2:
        raise IdentityError("graph worker task name is not reversible")
    try:
        node_id = bytes.fromhex(encoded).decode()
    except (UnicodeDecodeError, ValueError) as error:
        raise IdentityError("graph worker task name is not reversible") from error
    if not node_id or task_name(node_id, attempt) != name:
        raise IdentityError("graph worker task name is not canonical")
    return node_id


def active_nodes(active_wave: Any, nodes: dict[str, Any], revision: int) -> set[str]:
    if active_wave is None:
        return set()
    if not isinstance(active_wave, dict):
        raise IdentityError("graph.active_wave must be an object")
    if active_wave.get("id") != f"wave-{revision}" or active_wave.get("revision") != revision:
        raise IdentityError("graph.active_wave identity must match the root revision")
    wave_nodes = active_wave.get("nodes")
    if (
        not isinstance(wave_nodes, list)
        or not wave_nodes
        or any(not isinstance(item, str) for item in wave_nodes)
        or len(wave_nodes) != len(set(wave_nodes))
    ):
        raise IdentityError("graph.active_wave.nodes must be a non-empty unique array")
    if any(node_id not in nodes or nodes[node_id]["status"] != "running" for node_id in wave_nodes):
        raise IdentityError("graph.active_wave must contain known running nodes")
    return set(wave_nodes)
