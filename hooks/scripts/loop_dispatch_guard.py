#!/usr/bin/env python3
"""Authorize native Claude graph dispatch before implementation starts."""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, read_payload
from hooks.scripts.lib.agentic_loop_path import resolve_path, sanitise_session_id
from hooks.scripts.lib.graph_dispatch import authorize_dispatch, validate_dispatch_evals
from hooks.scripts.lib.graph_evidence import ENVELOPE_KEY
from hooks.scripts.lib.loop_state_common import read_state


def sandbox_worker(command: object) -> bool:
    """Recognize the native Python sandbox launcher without executing command text."""
    if not isinstance(command, str):
        return False
    try:
        return any(token.endswith("scripts/sandbox/spawn_sandboxed_worker.py") for token in shlex.split(command))
    except ValueError:
        return "scripts/sandbox/spawn_sandboxed_worker.py" in command


def check(payload: dict[str, Any]) -> None:
    """Fail closed for graph-owned work while leaving unrelated calls outside scope."""
    tool = payload.get("tool_name")
    request = payload.get("tool_input", {})
    if not isinstance(request, dict):
        return
    request = cast(dict[str, Any], request)
    agent = tool == "Agent"
    role = request.get("subagent_type", "")
    role = role if isinstance(role, str) else ""
    worker = (agent and role == "coderails:loop-worker") or (tool == "Bash" and sandbox_worker(request.get("command")))
    if not agent and not worker:
        return
    prompt = request.get("prompt", "")
    prompt = prompt if isinstance(prompt, str) else ""
    marked = ENVELOPE_KEY in prompt
    session = sanitise_session_id(str(payload.get("session_id", "")))
    path = resolve_path(str(payload.get("cwd") or os.getcwd()), session)
    state = read_state(path)
    if not state:
        if worker or marked:
            raise ValueError("no owned progress.json was found before native dispatch")
        return
    if state.get("session_id") != session:
        raise ValueError("progress.json belongs to another session")
    if agent and ("graph" in state or marked):
        authorize_dispatch(path, session, prompt, role)
    elif worker:
        if state.get("schema_version") != 3 or not state.get("loop_id"):
            raise ValueError("implementation workers require current loop identity")
        validate_dispatch_evals(path, state, "U3", worker=True)


def main() -> int:
    """Emit a native PreToolUse denial while retaining the hook's zero exit code."""
    try:
        check(cast(dict[str, Any], read_payload()))
    except (ValueError, OSError, KeyError, TypeError) as error:
        log(f"hook=loop_dispatch_guard blocked=1 reason={error}")
        deny(f"[loop-dispatch-guard] Blocked: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
