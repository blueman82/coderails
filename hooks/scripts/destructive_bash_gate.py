#!/usr/bin/env python3
"""Deny destructive Bash requests and source writes against protected branches."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import RESOURCE_MESSAGE, HostResourceError, deny, output, read_payload_strict
from hooks.scripts.lib.destructive_patterns import normalize_ifs, permanent_pattern, source_write, workflow_substitution
from hooks.scripts.lib.destructive_routes import ROUTES


def main() -> int:
    """Evaluate the input command without running any of its contents."""
    try:
        payload = read_payload_strict()
    except HostResourceError:
        deny(RESOURCE_MESSAGE)  # fail closed: a gate that cannot read its input must not allow the action
        return 0
    tool_input = payload.get("tool_input")
    raw = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(raw, str) or not raw:
        return 0
    command = normalize_ifs(raw)
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) and cwd_value else os.getcwd()
    pattern, identifier = permanent_pattern(command, cwd)
    if pattern:
        output(
            "PreToolUse",
            permissionDecision="deny",
            patternId=identifier,
            permissionDecisionReason=f"Destructive pattern detected: {pattern}\n"
            f"Full command: {command}\n"
            f"This command is permanently blocked. {ROUTES[identifier]}",
        )
        return 0
    if reason := source_write(command, cwd):
        deny(reason)
        return 0
    if workflow_substitution(command):
        deny(
            "Command-substitution character (backtick, $(...), or process substitution <(...)/>(...)) "
            "detected inside a push.py/merge.py/post_review.py/post_evals.py argument.\n"
            f"Full command: {command}\n"
            "These scripts take a free-text message that becomes a commit/PR title or comment body — "
            "a backtick, $(...), or <(...)/>(...) in it executes as live shell substitution when this line runs, "
            "not literal text. Rewrite the argument in plain prose with no backticks, $(), or <()/>()."
        )
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("destructive_bash_gate", main))
