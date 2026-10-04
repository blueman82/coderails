#!/usr/bin/env python3
"""Opt-in action-receipt gate: gh pr merge and git push to main/master need a matching receipt.

Config `action_authority`: enforce | advisory; absent, unreadable or anything else is off (silent exit 0).
Advisory traces and warns, never denies. Enforce denies only when no receipt verifies. Any own error fails open
with reason action_authority_failed_open. It does not touch pr_merge_gate, destructive_bash_gate or
enforce_pr_workflow. Limits: the hash covers only the command text seen here (not env, aliases, bash -c wrappers,
implicit-upstream push); a receipt does not prove a human minted it.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.pr_workflow_match import operation, targets_main
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.action_receipt import find_valid, proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.config import config_path, config_value

GUARDED = {"merge", "git_push"}


def mode(cwd: str) -> str:
    """Return enforce, advisory or off, never raising."""
    path = config_path(cwd)
    value = config_value(path, "action_authority") if path else ""
    return value if value in {"enforce", "advisory"} else "off"


def main() -> int:
    """Check one Bash payload; fail open on any own error."""
    payload = read_payload()
    session = str(payload.get("session_id") or "")
    try:
        data = payload.get("tool_input")
        command = data.get("command") if isinstance(data, dict) else None
        if not isinstance(command, str) or not command:
            return 0
        cwd = str(payload.get("cwd") or os.getcwd())
        name, segment, target = operation(command)
        if name not in GUARDED or (mode_ := mode(cwd)) == "off" or not targets_main(command, cwd, target, name):
            return 0
        authority = read_authority(session)
        loop_id = authority["loop_id"] if authority else None
        branch = git_output(cwd, "branch", "--show-current")
        proposed = proposed_action(name, segment, cwd, branch)
        found, code = find_valid(session, proposed, datetime.now(timezone.utc), loop_id, consume_it=mode_ == "enforce")
        if found is not None:
            if mode_ == "enforce":
                append_row("action_authority", "allowed", "receipt_consumed", session, loop_id)
            return 0
        if mode_ == "advisory":
            append_row("action_authority", "advisory", f"advisory_{code}", session, loop_id)
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_row("action_authority", "denied", f"denied_{code}", session, loop_id)
        deny(
            f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). Mint one for this exact command: "
            f"python3 scripts/action_receipt_cli.py approve-action --session {session} --kind {name} "
            f"--command '<exact command>'. Or set action_authority to off."
        )
    except Exception:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_row("action_authority", "failed_open", "action_authority_failed_open", session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
