"""One-way boundary between retained native graph history and driver waves."""

from __future__ import annotations

import copy
from typing import Any


def valid(graph: dict[str, Any], revision: int) -> bool:
    """Accept absent mode or one internally consistent driver cutover."""
    keys = ("dispatch_mode", "native_last_revision", "driver_from_revision")
    if not any(key in graph for key in keys):
        return True
    last, first = graph.get("native_last_revision"), graph.get("driver_from_revision")
    return (
        graph.get("dispatch_mode") == "driver"
        and type(last) is int
        and type(first) is int
        and last >= 1
        and first == last + 2
        and first <= revision + 1
    )


def require_valid(graph: dict[str, Any], revision: int) -> None:
    """Reject a partial or inconsistent cutover marker."""
    if not valid(graph, revision):
        raise ValueError("graph has an invalid driver cutover")


def cutover(state: dict[str, Any]) -> dict[str, Any]:
    """Propose a cutover after the caller has validated state and native history."""
    root = copy.deepcopy(state)
    graph = root["graph"]
    if graph.get("dispatch_mode") is not None:
        raise ValueError("graph already has a dispatch cutover")
    if graph["active_wave"] is not None:
        raise ValueError("finish the active wave before driver cutover")
    if root.get("status") != "in-progress":
        raise ValueError("driver cutover requires an in-progress graph")
    last = root["revision"]
    root["revision"] += 1
    graph.update(dispatch_mode="driver", native_last_revision=last, driver_from_revision=last + 2)
    return {"state": root, "driver_from_revision": last + 2}
