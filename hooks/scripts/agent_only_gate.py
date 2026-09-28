#!/usr/bin/env python3
"""Nudge top-level do-work calls toward an Agent dispatch."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, output, read_payload

CARVE = re.compile(
    r"^\s*(?:gh|git|(?:bash|sh|python3?|\./)?\s*(?:\S*/)?scripts/"
    r"(?:push|merge|post_review|post_evals)\.(?:sh|py))(?:\s+.*)?$"
)
META = re.compile(r"[&;|`<>]|\$\(")


def main() -> int:
    """Nudge eligible top-level tool calls while preserving workflow carve-outs."""
    payload = read_payload()
    tool = payload.get("tool_name")
    if not isinstance(tool, str) or not tool:
        log("hook=agent_only_gate decision=allow reason=unparseable_or_missing_tool_name mode=fail-open")
        return 0
    if isinstance(payload.get("agent_id"), str) and payload["agent_id"]:
        return 0
    data = payload.get("tool_input")
    command = data.get("command", "") if isinstance(data, dict) and tool == "Bash" else ""
    carve = (
        isinstance(command, str) and "\n" not in command and not META.search(command) and bool(CARVE.fullmatch(command))
    )
    if carve:
        log(f"hook=agent_only_gate decision=silent tool={tool} carve_out=1")
        return 0
    if os.environ.get("AGENT_ONLY_GATE_ENFORCE") == "1":
        log(f"hook=agent_only_gate decision=deny tool={tool} mode=enforce")
        deny(
            f"Blocked: '{tool}' called inline in the top-level orchestrator session. "
            "AGENT_ONLY_GATE_ENFORCE=1 requires do-work calls to be dispatched to an Agent."
        )
    else:
        log(f"hook=agent_only_gate decision=nudge tool={tool} mode=warn carve_out=0")
        output(
            "PreToolUse",
            additionalContext=(
                f"[agent-only-gate] '{tool}' is running inline in the top-level orchestrator session. "
                "Consider dispatching do-work to an Agent instead."
            ),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
