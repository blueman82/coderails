#!/usr/bin/env python3
"""Action-receipt gate: warn by default; explicit enforce needs a signed receipt.

Config `action_authority`: advisory (default, also with no config or no key) | enforce | off; any other value is
enforce, traced action_authority_bad_mode. Advisory traces and warns, never denies. Enforce denies unless
authority.permits() allows and a receipt verifies (scripts/lib/receipt_gate.py, shared with merge.py, which is
independently fail-closed). Any own error fails open with reason action_authority_failed_open. It does not touch
pr_merge_gate, destructive_bash_gate or enforce_pr_workflow. Limits: the hash covers only the command text seen here
(not aliases, functions, xargs, scripts that push; sudo/subshell/bash -c/eval/gh api wrappers, quoting and absolute
program paths are normalised by guarded_segments, an env assignment prefix is kept and makes the command unbindable).
The mode is read from the in-repo config, which the agent can edit: `off` is a same-user switch, not a boundary. Each
enforce use is claimed by an atomic O_EXCL marker and the claim decides allow vs deny.
A receipt is signed (ssh-keygen, namespace coderails-receipt) and bound to repository+ref+sha; with the user-tier
trust root that is a cooperating-agent safeguard, not a boundary (docs/decisions/p3-human-only-minting.md).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.pr_workflow_match import MERGE_SCRIPT, guarded_segments, pr_number, state_mutated_before_guard
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.action_binding import binding
from scripts.lib.action_receipt import proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.receipt_gate import check_and_consume, resolve_mode
from scripts.lib.receipt_signing import USER_TIER, resolve_trust_root


def mode(cwd: str) -> str:
    """Return advisory (the default), enforce or off, never raising."""
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
        "The OWNER mints one at a terminal (it is signed with their passphrase key; an agent cannot): "
        f"python3 scripts/action_receipt_cli.py approve-action --session {session} --kind {name} "
        "--command '<exact command>' --cwd <directory it runs in>. "
        "One-time key setup: scripts/authority_keys.py init."
    )


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
        mode_, bad = resolve_mode(cwd)
        if mode_ == "off" or not (segments := guarded_segments(command, cwd)):
            return 0
        authority = read_authority(session)
        loop_id = authority["loop_id"] if authority else None
        if bad:
            append_row("action_authority", "advisory", "action_authority_bad_mode", trace_id, loop_id)
        signers, tier = resolve_trust_root()

        def claimed(_name: str) -> None:
            if tier == USER_TIER:
                append_row("action_authority", "allowed", USER_TIER, trace_id, loop_id)
            append_row("action_authority", "allowed", "receipt_consumed", trace_id, loop_id)

        missing = check_and_consume(
            session, [proposal(*segment) for segment in segments], None, loop_id, signers,
            consume=mode_ == "enforce", stale=state_mutated_before_guard(command), on_claim=claimed,
        )  # fmt: skip
        if missing is None:
            return 0
        name, code = missing
        if mode_ == "advisory":
            append_row("action_authority", "advisory", f"advisory_{code}", trace_id, loop_id)
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_row("action_authority", "denied", f"denied_{code}", trace_id, loop_id)
        deny(
            f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). "
            f"{how_to_proceed(code, session, name)}"
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
