#!/usr/bin/env python3
"""Action-receipt gate, ON by default (Codex copy of hooks/scripts/action_authority_gate.py).

Config `action_authority`: enforce (default, also with no config or no key) | advisory | off; any other value is
enforce, traced action_authority_bad_mode. Advisory traces and warns, never denies; enforce denies unless
authority.permits() allows and a receipt verifies (mirrored scripts/lib/receipt_gate.py, shared with merge.py, which is
independently fail-closed); any own error fails open (action_authority_failed_open). Receipts are signed and bound to
repository+ref+sha; with the user-tier trust root that is a cooperating-agent safeguard, not a boundary. The hash
covers only the command text seen here.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, cast

from hook_common import append_trace_row, deny, payload_object, read_input, text_field
from lib.action_match import MERGE_SCRIPT, guarded_segments, pr_number, state_mutated_before_guard
from lib.destructive_patterns import git_output

from scripts.lib.action_binding import binding
from scripts.lib.action_receipt import proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.receipt_gate import check_and_consume, resolve_mode
from scripts.lib.receipt_signing import USER_TIER, resolve_trust_root


def mode(cwd: str) -> str:
    """Return enforce (the default), advisory or off, never raising."""
    return resolve_mode(cwd)[0]


def proposal(name: str, segment: str, where: str) -> tuple[str, dict[str, Any]]:
    """The action as seen here, plus the PR number of a merge.py segment (merge.py matches on it)."""
    branch = git_output(where, "branch", "--show-current")
    proposed = proposed_action(name, segment, where, branch, binding(name, segment, where))
    script = name == "merge" and bool(re.search(MERGE_SCRIPT, segment))
    return name, proposed | {"script": script, "number": pr_number(segment) if script else ""}


def how_to_proceed(code: str, session: str, name: str) -> str:
    """The remedy for one refusal code."""
    if code in {"authority_denied", "max_prs_exceeded"}:
        return "The session's authority forbids it (authority.py inspect); a receipt cannot override that."
    if code == "no_session":
        return "The payload has no session_id, so no receipt can be bound."
    if code in {"binding_unknown", "state_mutated_before_guard"}:
        return (
            "Use the exact forms `git push <remote> <ref>` (no env prefix, -c or --git-dir) and `gh pr merge <n> "
            "--match-head-commit <head sha>`, with no earlier ref-moving step in the same command."
        )
    return (
        "The OWNER mints one at a terminal (signed with their passphrase key; an agent cannot): run "
        f"scripts/action_receipt_cli.py approve-action --session {session} --kind {name} "
        "--command '<exact command>' --cwd <directory it runs in>. "
        "One-time key setup: scripts/authority_keys.py init."
    )


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
        if not isinstance(command, str) or not command:
            return 0
        mode_, bad = resolve_mode(cwd)
        if mode_ == "off" or not (segments := guarded_segments(command, cwd)):
            return 0
        authority = read_authority(session) or {}
        loop_id = authority.get("loop_id")
        loop = loop_id if isinstance(loop_id, str) else None
        if bad:
            append_trace_row("action_authority", "advisory", "action_authority_bad_mode", trace_id, {"loop_id": loop})
        signers, tier = resolve_trust_root()
        missing = check_and_consume(
            session, [proposal(*segment) for segment in segments], datetime.now(timezone.utc), loop, signers,
            consume=mode_ == "enforce", stale=state_mutated_before_guard(command),
        )  # fmt: skip
        if missing is None:
            if mode_ == "enforce":
                if tier == USER_TIER:  # the allow rests on the agent-writable tier: a cooperating-agent safeguard
                    append_trace_row("action_authority", "allowed", USER_TIER, trace_id, {"loop_id": loop})
                append_trace_row("action_authority", "allowed", "receipt_consumed", trace_id, {"loop_id": loop})
            return 0
        name, code = missing
        if mode_ == "advisory":
            append_trace_row("action_authority", "advisory", f"advisory_{code}", trace_id, {"loop_id": loop})
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_trace_row("action_authority", "denied", f"denied_{code}", trace_id, {"loop_id": loop})
        deny(
            f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). "
            f"{how_to_proceed(code, session, name)}"
        )
    except Exception as error:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_trace_row(
            "action_authority", "failed_open", "action_authority_failed_open", trace_id,
            {"loop_id": loop, "inputs": {"error_class": type(error).__name__}},
        )  # fmt: skip
        print(f"action_authority failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
