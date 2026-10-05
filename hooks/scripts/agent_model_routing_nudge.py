#!/usr/bin/env python3
"""Advise an Agent model override from literal task-language signals."""

from __future__ import annotations

import json
import os
import re
import select
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

READ_TIMEOUT_SECONDS = 5.0
MECHANICAL_PATTERN = re.compile(
    r"\b(rename|format|formatting|boilerplate|scaffold|reformat|relabel|find\s*[/-]?replace)\b", re.IGNORECASE
)
COMPLEX_PATTERN = re.compile(r"\b(design|architecture|architectural|redesign|re-architect)\b", re.IGNORECASE)


def read_stdin_payload(timeout: float = READ_TIMEOUT_SECONDS) -> str:
    """Read stdin without waiting indefinitely for an orphaned parent process."""
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    return sys.stdin.read() if ready else ""


def log_line(message: str) -> None:
    """Append a best-effort discipline log entry without changing hook output."""
    log_path = Path(os.environ.get("CLAUDE_DISCIPLINE_LOG", Path.home() / ".claude" / "discipline.log"))
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except OSError:
        pass


def payload_object(raw_payload: str) -> dict[str, object]:
    """Return a mapping payload, degrading malformed hook input to an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload) if raw_payload else {}
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def main() -> int:
    """Print advisory context only for an unambiguous Agent signal."""
    payload = payload_object(read_stdin_payload())
    if payload.get("tool_name") != "Agent":
        return 0
    candidate = payload.get("tool_input")
    if not isinstance(candidate, dict):
        return 0
    tool_input = cast(dict[str, object], candidate)
    if tool_input.get("model"):
        return 0
    text = " ".join(
        value for value in (tool_input.get("description"), tool_input.get("prompt")) if isinstance(value, str)
    )
    if not text:
        return 0
    is_mechanical = bool(MECHANICAL_PATTERN.search(text))
    is_complex = bool(COMPLEX_PATTERN.search(text))
    if is_mechanical == is_complex:
        log_line("hook=agent_model_routing_nudge nudged=0 reason=no_or_ambiguous_signal")
        return 0
    suggestion = "haiku" if is_mechanical else "opus"
    rationale = (
        "mechanical/rote-sounding task (rename/format/boilerplate-class wording)"
        if is_mechanical
        else "complex/architectural-sounding task (design/architecture/redesign-class wording)"
    )
    log_line(f"hook=agent_model_routing_nudge nudged=1 suggestion={suggestion}")
    context = (
        "[agent-model-routing-nudge] This Agent dispatch looks like a "
        f"{rationale} with no model override. Defaulting to sonnet is fine, but consider adding "
        f'model: "{suggestion}" to the Agent call if that better matches the task\'s actual depth. '
        "Advisory only — this is a cost/latency suggestion (see AGENTS.md's model-role-routing ceiling note), "
        "not a correctness requirement."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("agent_model_routing_nudge", main))
