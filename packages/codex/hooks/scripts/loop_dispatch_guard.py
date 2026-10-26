#!/usr/bin/env python3
"""Authorize every native spawn_agent of a graph-bound Codex session against its begin-wave dispatch record."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import cast

from hook_common import (
    RESOURCE_MESSAGE,
    HostResourceError,
    append_trace_row,
    deny,
    graph_output,
    graph_path,
    log,
    loop_state_path,
    payload_object,
    read_input,
    safe_session,
    text_field,
)

from scripts.lib.config import config_path
from scripts.lib.config_strict import ConfigRejected, strict_settings

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills/agentic-loop/scripts"))
from graph_encrypted_content import is_opaque  # noqa: E402
from graph_recovery import trace as recovery_trace  # noqa: E402

ENVELOPE_KEY = "CODERAILS_GRAPH_DISPATCH"
MAX_ENVELOPE_LINE = 8192
GRAPH_TASK = re.compile(r"^loop_worker_[0-9a-f]+_[0-9a-f]+(?:_a[1-9][0-9]*)?$")


def object_field(payload: dict[str, object], name: str) -> dict[str, object]:
    """Return a mapping field or an empty mapping."""
    value = payload.get(name)
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def dispatch_id(message: str) -> str:
    """Read a bounded first-line id; return empty for unreadable JSON and refuse oversized headers."""
    first = message.split("\n", 1)[0]
    if not first.startswith(ENVELOPE_KEY + "="):
        return ""
    if len(first) > MAX_ENVELOPE_LINE:
        raise ValueError("graph dispatch envelope line exceeds its limit")
    try:
        found = json.loads(first.split("=", 1)[1]).get("dispatch_id")
    except (ValueError, AttributeError):
        return ""
    return found if isinstance(found, str) else ""


def _remaining_budget(deadline: float) -> float:
    """Return time left for all graph discovery and authorization work."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("native graph check exceeded the hook budget")
    return remaining


def _bounded_graph_output(graph: Path, deadline: float, *arguments: str) -> dict[str, object] | None:
    """Spend the same hook budget on each graph command."""
    return graph_output(graph, *arguments, timeout_seconds=_remaining_budget(deadline))


def _refuse(code: str, message: str, session_id: object = None) -> None:
    """Deny and trace without using an unsafe native id as a path."""
    owner = session_id if isinstance(session_id, str) and safe_session(session_id) else "invalid-dispatch"
    inputs = {"session_id": session_id} if isinstance(session_id, str) else {}
    append_trace_row("loop_dispatch_guard", "refused", code, owner, {"inputs": inputs})
    log(f"hook=loop_dispatch_guard outcome=refused reason_code={code}")
    deny(f"{message} [reason_code={code}].")


def _discover(cwd: str, session_id: str, deadline: float) -> tuple[bool, Path | None]:
    """Separate proven graph absence from discovery errors."""
    try:
        config = config_path(cwd, strict=True, timeout_seconds=_remaining_budget(deadline))
        if config:
            strict_settings(config, session_id)
        state = loop_state_path(cwd, session_id, strict=True, timeout_seconds=_remaining_budget(deadline))
        _remaining_budget(deadline)
        return True, state
    except ConfigRejected:
        _refuse("dispatch_config_invalid", "Graph worker dispatch requires valid workflow configuration", session_id)
    except (subprocess.TimeoutExpired, TimeoutError):
        _refuse("dispatch_discovery_timeout", "Graph worker dispatch discovery timed out", session_id)
    except OSError as error:
        code = (
            "dispatch_discovery_ambiguous" if "more than one graph state" in str(error) else "dispatch_discovery_error"
        )
        _refuse(code, "Graph worker dispatch could not verify graph or config discovery", session_id)
    return False, None


def _graph_call(
    graph: Path, deadline: float, session_id: str, *arguments: str
) -> tuple[bool, dict[str, object] | None]:
    """Bound each graph command and report a timeout separately from invalid state."""
    try:
        return True, _bounded_graph_output(graph, deadline, *arguments)
    except (subprocess.TimeoutExpired, TimeoutError):
        _refuse("dispatch_graph_timeout", "Graph worker dispatch graph check timed out", session_id)
    except HostResourceError:
        _refuse("dispatch_graph_resource_error", RESOURCE_MESSAGE, session_id)
    return False, None


def _trace_graph_refusal(path: Path, inspection: dict[str, object], code: str) -> None:
    """Record a hook-side refusal in the graph's recovery sidecar."""
    state = {
        "session_id": inspection.get("session_id"),
        "loop_id": inspection.get("loop_id"),
        "revision": inspection.get("revision"),
        "graph": {"active_wave": inspection.get("active_wave")},
    }
    recovery_trace(path, state, "refused", code, {}, [(None, None, None)], "authorize-dispatch")


def _refuse_opaque(path: Path, inspection: dict[str, object], message: str, session_id: str) -> bool:
    """Refuse a message whose hidden instructions cannot be checked."""
    if not is_opaque(message):
        return False
    _trace_graph_refusal(path, inspection, "dispatch_prompt_unverifiable")
    _refuse(
        "dispatch_prompt_unverifiable", "Graph worker dispatch cannot verify encrypted prompt instructions", session_id
    )
    return True


def _identity(payload: dict[str, object]) -> tuple[str, str] | None:
    """Refuse malformed or unsafe native identity before any path lookup."""
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    if not isinstance(session_id, str) or not session_id.strip():
        code = "dispatch_session_required"
    elif not safe_session(session_id):
        code = "dispatch_unsafe_session"
    elif not isinstance(cwd, str) or not cwd.strip():
        code = "dispatch_cwd_required"
    else:
        return session_id, cwd
    _refuse(code, "Graph worker dispatch requires a safe session id and working directory", session_id)
    return None


def _check() -> int:
    """Check one native spawn against graph ownership and its single-use dispatch record."""
    deadline = time.monotonic() + 7.0
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
    identity = _identity(payload)
    if identity is None:
        return 0
    session_id, cwd = identity
    discovered, state = _discover(cwd, session_id, deadline)
    if not discovered:
        return 0
    if state is None:
        if enveloped or graph_named:
            _refuse("dispatch_graph_missing", "Graph worker dispatch requires this session's progress.json", session_id)
        return 0  # no loop owns this session: nothing to bind the spawn to
    graph = graph_path()
    if not graph.is_file():
        _refuse(
            "dispatch_graph_helper_missing",
            "Graph worker dispatch requires the provider-local graph helper",
            session_id,
        )
        return 0
    checked, inspection = _graph_call(graph, deadline, session_id, "inspect", str(state))
    if not checked:
        return 0
    if inspection is None:
        _refuse(
            "dispatch_graph_state_invalid",
            "Graph worker dispatch requires valid provider-local graph state",
            session_id,
        )
        return 0
    if inspection.get("status") == "complete":
        _refuse("dispatch_graph_complete", "A completed graph cannot dispatch native workers", session_id)
        return 0
    if _refuse_opaque(state, inspection, message, session_id):
        return 0
    agent_type = tool_input.get("agent_type")
    try:
        with tempfile.TemporaryDirectory() as scratch:
            message_file = Path(scratch) / "message.txt"
            message_file.write_text(message, encoding="utf-8")
            checked, authorization = _graph_call(
                graph,
                deadline,
                session_id,
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
                text_field(payload, "tool_use_id"),
            )
    except OSError:
        _trace_graph_refusal(state, inspection, "dispatch_message_unavailable")
        log(f"hook=loop_dispatch_guard session={session_id} blocked=1 reason_code=dispatch_message_unavailable")
        deny("Graph worker dispatch could not stage its message [reason_code=dispatch_message_unavailable].")
        return 0
    if not checked:
        return 0
    if authorization is None:
        _refuse(
            "dispatch_authorization_refused",
            "Graph worker dispatch needs the begin-wave envelope and contract sections pasted verbatim, "
            "the recorded task_name, an unused dispatch id and the role's own agent_type "
            "(see recovery-trace.jsonl beside progress.json)",
            session_id,
        )
        return 0
    log(
        "hook=loop_dispatch_guard "
        f"session={session_id} loop={text_field(authorization, 'loop_id')} "
        f"wave={text_field(authorization, 'wave_id')} task={task} blocked=0"
    )
    return 0


def main() -> int:
    """Treat any hook input or local runtime error as a denied spawn."""
    try:
        return _check()
    except (RecursionError, ValueError):
        _refuse("dispatch_input_invalid", "Graph worker dispatch input is malformed")
    except Exception:
        _refuse("dispatch_hook_error", "Graph worker dispatch could not complete its check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
