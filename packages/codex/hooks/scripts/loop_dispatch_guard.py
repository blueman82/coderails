#!/usr/bin/env python3
"""Authorize native graph worker dispatch only for the active Codex wave."""

from __future__ import annotations

import re
from typing import cast

from hook_common import (
    deny,
    graph_output,
    graph_path,
    log,
    loop_state_path,
    payload_object,
    read_input,
    text_field,
)

TASK_NAME = re.compile(r"loop_worker_[0-9a-f]+(?:_a[2-9][0-9]*)?$")


def object_field(payload: dict[str, object], name: str) -> dict[str, object]:
    """Return a mapping field or an empty mapping."""
    value = payload.get(name)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def main() -> int:
    """Deny worker dispatches that do not own this session's active graph wave."""
    payload = payload_object(read_input())
    if text_field(payload, "tool_name") != "spawn_agent":
        deny("Codex graph workers must use native spawn_agent.")
        return 0
    tool_input = object_field(payload, "tool_input")
    if tool_input.get("agent_type") != "loop-worker":
        return 0
    message = tool_input.get("message")
    first_line = message.splitlines()[0] if isinstance(message, str) and message else ""
    marker = first_line.removeprefix("CODERAILS_GRAPH_TASK=")
    if not TASK_NAME.fullmatch(marker) or first_line != f"CODERAILS_GRAPH_TASK={marker}":
        deny("Graph worker dispatch requires a canonical CODERAILS_GRAPH_TASK marker on the first message line.")
        return 0
    session_id = text_field(payload, "session_id")
    cwd = text_field(payload, "cwd")
    if not session_id or not cwd:
        deny("Graph worker dispatch requires a session id and working directory.")
        return 0
    state = loop_state_path(cwd, session_id)
    if state is None:
        deny("Graph worker dispatch could not resolve this session's progress.json.")
        return 0
    if not state.is_file():
        deny("Graph worker dispatch requires this session's progress.json. Start the native graph before spawn_agent.")
        return 0
    graph = graph_path()
    if not graph.is_file():
        deny("Graph worker dispatch requires the provider-local graph helper.")
        return 0
    inspection = graph_output(graph, "inspect", str(state))
    if inspection is None:
        deny("Graph worker dispatch requires valid provider-local graph state.")
        return 0
    if inspection.get("status") == "complete":
        deny("A completed graph cannot dispatch graph workers.")
        return 0
    authorization = graph_output(
        graph,
        "authorize-dispatch",
        str(state),
        "--session",
        session_id,
        "--task",
        marker,
        "--evals",
        str(state.parent / "evals.json"),
    )
    if authorization is None:
        deny("Graph worker dispatch requires valid state, active-wave ownership, and graded loop evidence.")
        return 0
    log(
        "hook=loop_dispatch_guard "
        f"session={session_id} loop={text_field(authorization, 'loop_id')} "
        f"wave={text_field(authorization, 'wave_id')} task={marker} blocked=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
