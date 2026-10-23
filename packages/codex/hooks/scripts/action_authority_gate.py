#!/usr/bin/env python3
"""Opt-in action-receipt gate (Codex copy of hooks/scripts/action_authority_gate.py).

Config `action_authority`: enforce | advisory; anything else is off (silent). Advisory traces and warns, never
denies; enforce denies only when no receipt verifies; any own error fails open (action_authority_failed_open).
The hash covers only the command text seen here, and a receipt does not prove a human minted it.
"""

from __future__ import annotations

import os
import re
import subprocess
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
from lib.action_match import guarded_segments
from lib.destructive_patterns import git_output


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


def artifact_sha(name: str, segment: str, cwd: str) -> str | None:
    """HEAD for a push, the PR head (via gh) for a merge; None when unknowable (a sha-bound receipt then fails)."""
    if name == "git_push":
        return git_output(cwd, "rev-parse", "HEAD") or None
    number = next((t.strip("\"'") for t in segment.split()[3:] if re.match(r"^[\"']?[0-9]", t)), "")
    if not number:
        return None
    try:
        out = subprocess.run(
            ["gh", "pr", "view", number, "--json", "headRefOid", "-q", ".headRefOid"],
            cwd=cwd, capture_output=True, text=True, timeout=4, check=False,
        ).stdout.strip()  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return out or None


def main() -> int:
    """Check one Bash payload; every guarded segment needs its own receipt; fail open on any own error."""
    payload = payload_object(read_input())
    session = text_field(payload, "session_id")
    trace_id = session or "_no_session"
    loop: str | None = None
    try:
        data = payload.get("tool_input")
        command = cast(dict[str, object], data).get("command") if isinstance(data, dict) else None
        cwd = text_field(payload, "cwd") or os.getcwd()
        if not isinstance(command, str) or not command or (mode_ := mode(cwd)) == "off":
            return 0
        if not (segments := guarded_segments(command, cwd)):
            return 0
        state, authority = authority_state(session)
        loop_id = authority.get("loop_id") if state == "live" else None
        loop = loop_id if isinstance(loop_id, str) else None
        now = datetime.now(timezone.utc)
        proposals = [
            (name, receipt_proposed(name, segment, where, git_output(where, "branch", "--show-current"),
                                    artifact_sha(name, segment, where)))
            for name, segment, where in segments
        ]  # fmt: skip
        results = [(name, *receipt_find_valid(session, proposed, now, loop)) for name, proposed in proposals]
        missing = next(((name, code) for name, found, code in results if found is None), None)
        if missing is None and mode_ == "enforce":
            for name, proposed in proposals:  # the O_EXCL claim, not the verify above, decides who is allowed
                found, code = receipt_find_valid(session, proposed, now, loop, True)
                if found is None:
                    missing = (name, code)
                    break
        if missing is None:
            if mode_ == "enforce":
                append_trace_row("action_authority", "allowed", "receipt_consumed", trace_id, {"loop_id": loop})
            return 0
        name, code = missing
        if mode_ == "advisory":
            append_trace_row("action_authority", "advisory", f"advisory_{code}", trace_id, {"loop_id": loop})
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_trace_row("action_authority", "denied", f"denied_{code}", trace_id, {"loop_id": loop})
        how = (
            "The payload has no session_id, so no receipt can be bound."
            if code == "no_session"
            else "The receipt CLI (scripts/action_receipt_cli.py) is NOT shipped in the Codex package: run it from a "
            f"coderails repo checkout: approve-action --session {session} --kind {name} --command '<exact command>' "
            "--cwd <directory it runs in>."
        )
        deny(
            f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). {how} Or set action_authority to off."
        )
    except Exception as error:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_trace_row(
            "action_authority", "failed_open", "action_authority_failed_open", trace_id,
            {"loop_id": loop, "inputs": {"error_class": type(error).__name__}},
        )  # fmt: skip
        print(f"action_authority failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("action_authority_gate", main))
