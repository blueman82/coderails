#!/usr/bin/env python3
"""Deny destructive Bash requests and source writes against protected branches."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.destructive_patterns import normalize_ifs, permanent_pattern, source_write, workflow_substitution
from hooks.scripts.lib.destructive_routes import ROUTES
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.authority_permits import permits

LEASE = re.compile(r"\bgit\b.*\bpush\b.*--force-with-lease\b", re.I)  # the one family permanent_pattern can allow


def main() -> int:
    """Evaluate the input command without running any of its contents."""
    payload = read_payload()
    tool_input = payload.get("tool_input")
    raw = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(raw, str) or not raw:
        return 0
    command = normalize_ifs(raw)
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) and cwd_value else os.getcwd()
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
    session = str(payload.get("session_id") or "")
    flat = command.replace("\\\n", "").replace("\n", " ")  # the same flattening permanent_pattern decides on
    if LEASE.search(flat) and not (verdict := permits(session, "destructive_shell"))["allow"]:
        append_row("action_authority", "denied", "authority_denied_destructive_shell", session)
        deny(
            "authority_denied_destructive_shell: this session's authority denies destructive_shell, so the allowlisted "
            f"git push --force-with-lease is refused too ({verdict['reason']}). Full command: {command}"
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
    raise SystemExit(main())
