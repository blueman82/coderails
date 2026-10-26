#!/usr/bin/env python3
"""Authorize every native spawn_agent of a graph-bound Codex session against its begin-wave dispatch record."""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import cast

from hook_common import (
    RESOURCE_MESSAGE,
    HostResourceError,
    deny,
    graph_output,
    graph_path,
    log,
    loop_state_path,
    payload_object,
    read_input,
    text_field,
)

from scripts.lib.config import config_path
from scripts.lib.config_strict import ConfigRejected, strict_settings

ENVELOPE_KEY = "CODERAILS_GRAPH_DISPATCH"
GRAPH_TASK = re.compile(r"^loop_worker_[0-9a-f]+_[0-9a-f]+(?:_a[1-9][0-9]*)?$")


def object_field(payload: dict[str, object], name: str) -> dict[str, object]:
    """Return a mapping field or an empty mapping."""
    value = payload.get(name)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def dispatch_id(message: str) -> str:
    """The dispatch id on the first line, or empty when the envelope is absent or unreadable (the CLI then refuses)."""
    first = message.split("\n", 1)[0]
    if not first.startswith(ENVELOPE_KEY + "="):
        return ""
    try:
        found = json.loads(first.split("=", 1)[1]).get("dispatch_id")
    except (ValueError, AttributeError):
        return ""
    return found if isinstance(found, str) else ""


def main() -> int:
    """Deny any spawn in a graph-bound session that does not carry a valid, unused, role-correct envelope."""
    payload = payload_object(read_input())
    if text_field(payload, "tool_name") not in ("spawn_agent", "collaborationspawn_agent"):
        deny("Codex graph workers must use native spawn_agent.")
        return 0
    tool_input = object_field(payload, "tool_input")
    message = tool_input.get("message")
    message = message if isinstance(message, str) else ""
    task = tool_input.get("task_name")
    task = task if isinstance(task, str) else ""
    enveloped = message.startswith(ENVELOPE_KEY + "=")
    graph_named = bool(GRAPH_TASK.fullmatch(task))
    if "agent_type" in tool_input and (
        not isinstance(tool_input["agent_type"], str) or not tool_input["agent_type"].strip()
    ):
        deny("Graph worker dispatch requires a nonblank native role when agent_type is supplied.")
        return 0
    session_id = text_field(payload, "session_id")
    cwd = text_field(payload, "cwd")
    if not session_id or not cwd:
        if enveloped or graph_named:
            deny("Graph worker dispatch requires a session id and working directory.")
        return 0
    config = config_path(cwd)
    if config:
        try:
            strict_settings(config, session_id)
        except ConfigRejected as error:
            deny(f"Graph worker dispatch requires valid workflow configuration: {error}")
            return 0
    state = loop_state_path(cwd, session_id)
    if state is None or not state.is_file():
        if enveloped or graph_named:
            deny("Graph worker dispatch requires this session's progress.json. Start the native graph first.")
        return 0  # no loop owns this session: nothing to bind the spawn to
    tool_use_id = text_field(payload, "tool_use_id")
    if not tool_use_id:
        deny("Graph worker dispatch requires a native tool-call id.")
        return 0
    graph = graph_path()
    if not graph.is_file():
        deny("Graph worker dispatch requires the provider-local graph helper.")
        return 0
    try:
        inspection = graph_output(graph, "inspect", str(state))
    except HostResourceError:
        deny(RESOURCE_MESSAGE)
        return 0
    if inspection is None:
        deny("Graph worker dispatch requires valid provider-local graph state.")
        return 0
    if inspection.get("status") == "complete":
        if enveloped or graph_named:
            deny("A completed graph cannot dispatch graph workers.")
        return 0
    agent_type = tool_input.get("agent_type")
    with tempfile.TemporaryDirectory() as scratch:
        message_file = Path(scratch) / "message.txt"
        message_file.write_text(message, encoding="utf-8")
        try:
            authorization = graph_output(
                graph,
                "authorize-dispatch",
                str(state),
                "--session",
                session_id,
                "--dispatch-id",
                dispatch_id(message),
                "--message-file",
                str(message_file),
                "--agent-type",
                agent_type if isinstance(agent_type, str) else "",
                "--task-name",
                task,
                "--tool-use-id",
                tool_use_id,
            )
        except HostResourceError:
            deny(RESOURCE_MESSAGE)
            return 0
    if authorization is None:
        deny(
            "Graph worker dispatch needs the begin-wave envelope and contract sections pasted verbatim, "
            "the recorded task_name, an unused dispatch id and the role's own agent_type "
            "(reason code: recovery-trace.jsonl beside progress.json)."
        )
        return 0
    log(
        "hook=loop_dispatch_guard "
        f"session={session_id} loop={text_field(authorization, 'loop_id')} "
        f"wave={text_field(authorization, 'wave_id')} task={task} blocked=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
