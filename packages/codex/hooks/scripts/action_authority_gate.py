#!/usr/bin/env python3
"""Optional action-receipt gate (Codex copy of hooks/scripts/action_authority_gate.py).

Config `action_authority`: enforce | advisory; absent or anything else is off.
Advisory traces and warns, never denies; enforce denies only when no receipt verifies; any own error fails open
(action_authority_failed_open).
Receipts are signed and bound to repository+ref+sha (mirrored scripts/lib); with the user-tier trust root that is a
cooperating-agent safeguard, not a boundary. The hash covers only the command text seen here.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from hook_common import append_trace_row, deny, payload_object, read_input, text_field
from lib.action_match import guarded_segments, state_mutated_before_guard
from lib.destructive_patterns import git_output

from scripts.lib.action_binding import binding
from scripts.lib.action_receipt import claim_many, find_valid, proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.receipt_signing import USER_TIER, resolve_trust_root


def mode(cwd: str) -> str:
    """Read explicit advisory or enforce mode from the nearest workflow config."""
    probe = Path(cwd).resolve()
    for directory in (probe, *probe.parents):
        candidate = directory / ".coderails" / "workflow.config.yaml"
        if candidate.is_file():
            match = re.search(r"^action_authority:\s*[\"']?(\w+)", candidate.read_text(), re.MULTILINE)
            return match[1] if match and match[1] in {"enforce", "advisory"} else "off"
        if (directory / ".git").exists():
            break
    return "off"


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
        authority = read_authority(session) or {}
        loop_id = authority.get("loop_id")
        loop = loop_id if isinstance(loop_id, str) else None
        now = datetime.now(timezone.utc)
        proposals = [
            (name, proposed_action(name, segment, where, git_output(where, "branch", "--show-current"),
                                   binding(name, segment, where)))
            for name, segment, where in segments
        ]  # fmt: skip
        signers, tier = resolve_trust_root()
        unbound = next((name for name, proposed in proposals if proposed["artifact_sha"] is None), None)
        missing = (unbound, "binding_unknown") if unbound else None  # unknowable repository+ref+sha fails closed
        if missing is None and state_mutated_before_guard(command):  # the bound sha/ref would be stale at execution
            missing = (proposals[0][0], "state_mutated_before_guard")
        if missing is None:
            results = [(name, *find_valid(session, p, now, loop, signers=signers)) for name, p in proposals]
            missing = next(((name, code) for name, found, code in results if found is None), None)
        if missing is None and mode_ == "enforce":
            claimed, code, index = claim_many(session, [p for _, p in proposals], now, loop, signers=signers)
            if claimed is None:
                missing = (proposals[index][0], code)
            else:
                for _ in claimed:
                    if tier == USER_TIER:
                        append_trace_row("action_authority", "allowed", USER_TIER, trace_id, {"loop_id": loop})
                    append_trace_row("action_authority", "allowed", "receipt_consumed", trace_id, {"loop_id": loop})
        if missing is None:
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
            else (
                "Use the exact forms `git push <remote> <ref>` (no env prefix, -c or --git-dir) and `gh pr merge <n> "
                "--match-head-commit <head sha>`, with no earlier ref-moving step in the same command."
                if code in {"binding_unknown", "state_mutated_before_guard"}
                else "For optional receipt enforcement, sign one at a terminal with the configured key: run "
                f"scripts/action_receipt_cli.py approve-action --session {session} --kind {name} "
                "--command '<exact command>' --cwd <directory it runs in>. "
                "One-time key setup: scripts/authority_keys.py init."
            )
        )
        deny(f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). {how}")
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
