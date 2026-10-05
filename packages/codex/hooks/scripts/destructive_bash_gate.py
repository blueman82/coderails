#!/usr/bin/env python3
"""Deny destructive Bash requests and source writes against protected branches."""

from __future__ import annotations

import json
import os
import re
from typing import cast

from hook_common import deny, payload_object, read_input
from lib.destructive_patterns import normalize_ifs, permanent_pattern, source_write, workflow_substitution
from lib.destructive_routes import ROUTES


def main() -> int:
    """Evaluate the input command without running any of its contents."""
    payload = payload_object(read_input())
    tool_input = payload.get("tool_input")
    raw = cast(dict[str, object], tool_input).get("command") if isinstance(tool_input, dict) else None
    if not isinstance(raw, str) or not raw:
        return 0
    command = normalize_ifs(raw)
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) and cwd_value else os.getcwd()
    for token in re.findall(r"[a-zA-Z0-9_./-]+", command):
        normalized = os.path.abspath(os.path.join(cwd, token))
        if normalized.endswith(("/.codex/config.toml", "/.codex/requirements.toml")):
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "patternId": "codex-owner-config",
                            "permissionDecisionReason": "Destructive pattern detected: "
                            "native Codex owner configuration path\n"
                            f"Full command: {command}\nThis command is permanently blocked. "
                            "Safe route: these owner-only files must be changed by the owner outside this session.",
                        }
                    }
                )
            )
            return 0
    pattern, identifier = permanent_pattern(command, cwd)
    if pattern:
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "patternId": identifier,
                        "permissionDecisionReason": f"Destructive pattern detected: {pattern}\n"
                        f"Full command: {command}\n"
                        f"This command is permanently blocked. {ROUTES[identifier]}",
                    }
                }
            )
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
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("destructive_bash_gate", main))
