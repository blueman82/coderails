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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.pr_workflow_match import guarded_segments, pr_number
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.action_receipt import find_valid, proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.config import config_path, config_value


def mode(cwd: str) -> str:
    """Return enforce, advisory or off, never raising."""
    path = config_path(cwd)
    value = config_value(path, "action_authority") if path else ""
    return value if value in {"enforce", "advisory"} else "off"


def artifact_sha(name: str, segment: str, cwd: str) -> str | None:
    """The real artifact at enforcement time: HEAD for a push, the PR head for a merge; None when unknowable.

    A receipt minted with --artifact-sha verifies only when this equals it, so an unknowable sha fails closed.
    """
    if name == "git_push":
        return git_output(cwd, "rev-parse", "HEAD") or None
    number = pr_number(segment)
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
    payload = read_payload()
    session = str(payload.get("session_id") or "")
    trace_id = session or "_no_session"  # append_row refuses an empty id; keep the denial countable
    loop_id: str | None = None
    try:
        data = payload.get("tool_input")
        command = data.get("command") if isinstance(data, dict) else None
        if not isinstance(command, str) or not command:
            return 0
        cwd = str(payload.get("cwd") or os.getcwd())
        mode_ = mode(cwd)
        if mode_ == "off" or not (segments := guarded_segments(command, cwd)):
            return 0
        authority = read_authority(session)
        loop_id = authority["loop_id"] if authority else None
        now = datetime.now(timezone.utc)
        proposals = [
            (name, proposed_action(name, segment, where, git_output(where, "branch", "--show-current"),
                                   artifact_sha(name, segment, where)))
            for name, segment, where in segments
        ]  # fmt: skip
        results = [(name, *find_valid(session, proposed, now, loop_id)) for name, proposed in proposals]
        missing = next(((name, code) for name, found, code in results if found is None), None)
        if missing is None:
            if mode_ == "enforce":
                for _, proposed in proposals:  # only now spend the receipts: a later refusal costs none
                    find_valid(session, proposed, now, loop_id, consume_it=True)
                append_row("action_authority", "allowed", "receipt_consumed", trace_id, loop_id)
            return 0
        name, code = missing
        if mode_ == "advisory":
            append_row("action_authority", "advisory", f"advisory_{code}", trace_id, loop_id)
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_row("action_authority", "denied", f"denied_{code}", trace_id, loop_id)
        how = (
            "The payload has no session_id, so no receipt can be bound."
            if code == "no_session"
            else f"Mint one for this exact command: python3 scripts/action_receipt_cli.py approve-action "
            f"--session {session} --kind {name} --command '<exact command>' --cwd <directory it runs in>."
        )
        deny(
            f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). {how} Or set action_authority to off."
        )
    except Exception as error:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_row(
            "action_authority", "failed_open", "action_authority_failed_open", trace_id, loop_id,
            {"error_class": type(error).__name__},
        )  # fmt: skip
        print(f"action_authority failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
