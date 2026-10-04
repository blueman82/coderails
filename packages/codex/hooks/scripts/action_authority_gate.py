#!/usr/bin/env python3
"""Opt-in action-receipt gate (Codex copy of hooks/scripts/action_authority_gate.py).

Config `action_authority`: enforce | advisory; anything else is off (silent). Advisory traces and warns, never
denies; enforce denies only when no receipt verifies; any own error fails open (action_authority_failed_open).
The hash covers only the command text seen here, and a receipt does not prove a human minted it.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from hook_common import (
    append_trace_row,
    authority_state,
    deny,
    payload_object,
    read_input,
    receipt_find_valid,
    receipt_proposed,
    text_field,
)
from lib.destructive_patterns import git_output

GUARDED = (("merge", r"^gh\s+pr\s+merge(?:\s|$)"), ("git_push", r"^git\s+push(?:\s|$)"))


def mode(cwd: str) -> str:
    """Return enforce, advisory or off from the nearest .coderails/workflow.config.yaml, never raising."""
    probe = Path(cwd).resolve()
    for directory in (probe, *probe.parents):
        candidate = directory / ".coderails" / "workflow.config.yaml"
        if candidate.is_file():
            match = re.search(r"^action_authority:\s*[\"']?(\w+)", candidate.read_text(), re.MULTILINE)
            return match[1] if match and match[1] in {"enforce", "advisory"} else "off"
        if (directory / ".git").exists():
            break
    return "off"


def guarded(command: str, cwd: str) -> tuple[str, str]:
    """Return (operation, segment) for gh pr merge, or git push targeting main/master; else empty strings."""
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        segment = segment.lstrip()
        for name, pattern in GUARDED:
            if not re.search(pattern, segment):
                continue
            if name == "merge" or git_output(cwd, "branch", "--show-current") in {"main", "master"}:
                return name, segment
            if re.search(r"(^|\s)\+?(refs/heads/)?(main|master)([\s;&|)]|$)|:(refs/heads/)?(main|master)", segment):
                return name, segment
    return "", ""


def main() -> int:
    """Check one Bash payload; fail open on any own error."""
    payload = payload_object(read_input())
    session = text_field(payload, "session_id")
    try:
        data = payload.get("tool_input")
        command = cast(dict[str, object], data).get("command") if isinstance(data, dict) else None
        cwd = text_field(payload, "cwd") or os.getcwd()
        if not isinstance(command, str) or not command or (mode_ := mode(cwd)) == "off":
            return 0
        name, segment = guarded(command, cwd)
        if not name:
            return 0
        state, authority = authority_state(session)
        loop_id = authority.get("loop_id") if state == "live" else None
        proposed = receipt_proposed(name, segment, cwd, git_output(cwd, "branch", "--show-current"))
        loop = loop_id if isinstance(loop_id, str) else None
        found, code = receipt_find_valid(session, proposed, datetime.now(timezone.utc), loop, mode_ == "enforce")
        if found is not None:
            if mode_ == "enforce":
                append_trace_row("action_authority", "allowed", "receipt_consumed", session)
            return 0
        if mode_ == "advisory":
            append_trace_row("action_authority", "advisory", f"advisory_{code}", session)
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_trace_row("action_authority", "denied", f"denied_{code}", session)
        deny(
            f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). Mint one for this exact command: "
            f"python3 scripts/action_receipt_cli.py approve-action --session {session} --kind {name} "
            f"--command '<exact command>'. Or set action_authority to off."
        )
    except Exception:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_trace_row("action_authority", "failed_open", "action_authority_failed_open", session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
