"""Normalize graph state for standing-order source bindings."""

from __future__ import annotations

import copy
from typing import Any, cast


def source_state(state: dict[str, Any], codex: bool) -> dict[str, Any]:
    """Remove only fields changed by native completion, including its timestamp."""
    source = copy.deepcopy(state)
    if codex and state["status"] == "complete":
        completion = state.get("completion")
        if not isinstance(completion, dict):
            raise ValueError("order_source_invalid")
        completion = cast("dict[str, Any]", completion)
        if type(completion.get("revision")) is not int:
            raise ValueError("order_source_invalid")
        if completion["revision"] != state["revision"] - 1:
            raise ValueError("order_source_mismatch")
        source["revision"] = completion["revision"]
    elif "completion" in state:
        raise ValueError("order_source_invalid")
    for key in ("status", "completion", "completed_marker", "updated_at"):
        source.pop(key, None)
    if isinstance(counts := source.get("loop_stop_counts"), dict):
        remaining = {k: v for k, v in cast("dict[str, Any]", counts).items() if k != "complete"}
        source.pop("loop_stop_counts")
        source.update({"loop_stop_counts": remaining} if remaining else {})
    return source


def legacy_source_state(state: dict[str, Any], codex: bool) -> dict[str, Any] | None:
    """Restore the current timestamp only when checking an old receipt."""
    stamp = state.get("updated_at")
    if not isinstance(stamp, str) or not stamp:
        return None
    source = source_state(state, codex)
    source["updated_at"] = stamp
    return source
