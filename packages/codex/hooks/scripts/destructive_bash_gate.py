#!/usr/bin/env python3
"""Deny destructive Bash requests and source writes against protected branches."""

from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from typing import cast

from hook_common import append_trace_row, deny, payload_object, read_input, text_field
from lib.destructive_patterns import normalize_ifs, permanent_pattern, source_write, workflow_substitution
from lib.destructive_routes import ROUTES
from lib.shell_context import opaque_execution

from scripts.lib.authority_permits import permits

LEASE = re.compile(r"\bgit\b.*\bpush\b.*--force-with-lease\b", re.I)  # the one family permanent_pattern can allow


def mark() -> None:
    """Flag the deny printed by this hook so telemetry records cause deny, not ok."""
    with suppress(ImportError):  # telemetry must never be able to break the hook
        from lib.hook_telemetry import mark_deny

        mark_deny()


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
    if opaque_execution(command, cwd):
        deny("Blocked: executable shell body exceeds the guarded parser depth.")
        return 0
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
            mark()
            return 0
    try:
        pattern, identifier = permanent_pattern(command, cwd)
    except OSError:
        deny("Host resource exhaustion prevented this hook from checking the command. Retry; the action is blocked.")
        return 0
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
        mark()
        return 0
    session = text_field(payload, "session_id")
    flat = command.replace("\\\n", "").replace("\n", " ")  # the same flattening permanent_pattern decides on
    if LEASE.search(flat) and not (verdict := permits(session, "destructive_shell"))["allow"]:
        append_trace_row("action_authority", "denied", "authority_denied_destructive_shell", session)
        deny(
            "authority_denied_destructive_shell: this session's authority denies destructive_shell, so the allowlisted "
            f"git push --force-with-lease is refused too ({verdict['reason']}). Full command: {command}"
        )
        return 0
    try:
        reason = source_write(command, cwd)
    except OSError:
        deny("Host resource exhaustion prevented this hook from checking the command. Retry; the action is blocked.")
        return 0
    if reason:
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
