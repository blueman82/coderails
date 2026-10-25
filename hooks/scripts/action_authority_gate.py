#!/usr/bin/env python3
"""Optional action-receipt gate for gh pr merge and git push to main/master.

Config `action_authority`: enforce | advisory; absent, unreadable or anything else is off. Advisory traces and
warns, never denies. Enforce denies only when no receipt verifies. Host-resource exhaustion reading the payload
also denies; any other own error fails open with reason action_authority_failed_open. It does not touch
pr_merge_gate, destructive_bash_gate or enforce_pr_workflow. The hash covers the command text seen here;
guarded_segments normalises supported wrappers and rejects commands whose earlier steps move the bound ref.
Each enforce use is
claimed by an atomic O_EXCL marker and the claim, not the verify, decides allow vs deny.
A receipt is signed (ssh-keygen, namespace coderails-receipt) and bound to repository+ref+sha; with the user-tier
trust root that is a cooperating-agent safeguard, not a boundary (docs/decisions/p3-human-only-minting.md).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import RESOURCE_MESSAGE, HostResourceError, deny, read_payload_strict
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.pr_workflow_match import guarded_segments, state_mutated_before_guard
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.action_binding import binding
from scripts.lib.action_receipt import claim_many, find_valid, proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.config import config_path, config_value
from scripts.lib.receipt_signing import USER_TIER, resolve_trust_root


def mode(cwd: str) -> str:
    """Use receipts only when the repository explicitly enables advisory or enforce mode."""
    path = config_path(cwd)
    value = config_value(path, "action_authority") if path else ""
    return value if value in {"enforce", "advisory"} else "off"


def main() -> int:
    """Check one Bash payload; every guarded segment needs its own receipt; fail open on any own error."""
    try:
        payload = read_payload_strict()
    except HostResourceError:
        deny(RESOURCE_MESSAGE)  # fail closed: a gate that cannot read its input must not allow the action
        return 0
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
        if mode_ == "off" or not (segments := guarded_segments(command, cwd, implicit_push=True)):
            return 0
        authority = read_authority(session)
        loop_id = authority["loop_id"] if authority else None
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
            results = [(name, *find_valid(session, p, now, loop_id, signers=signers)) for name, p in proposals]
            missing = next(((name, code) for name, found, code in results if found is None), None)
        if missing is None and mode_ == "enforce":
            claimed, code, index = claim_many(session, [p for _, p in proposals], now, loop_id, signers=signers)
            if claimed is None:
                missing = (proposals[index][0], code)
            else:
                for _ in claimed:
                    if tier == USER_TIER:
                        append_row("action_authority", "allowed", USER_TIER, trace_id, loop_id)
                    append_row("action_authority", "allowed", "receipt_consumed", trace_id, loop_id)
        if missing is None:
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
            else (
                "Use the exact forms `git push <remote> <ref>` (no env prefix, -c or --git-dir) and `gh pr merge <n> "
                "--match-head-commit <head sha>`, with no earlier ref-moving step in the same command."
                if code in {"binding_unknown", "state_mutated_before_guard"}
                else "For optional receipt enforcement, sign one at a terminal with the configured key: "
                f"python3 scripts/action_receipt_cli.py approve-action --session {session} --kind {name} "
                "--command '<exact command>' --cwd <directory it runs in>. "
                "One-time key setup: scripts/authority_keys.py init."
            )
        )
        deny(f"Blocked: {name.replace('_', ' ')} needs an action receipt ({code}). {how}")
    except Exception as error:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_row(
            "action_authority", "failed_open", "action_authority_failed_open", trace_id, loop_id,
            {"error_class": type(error).__name__},
        )  # fmt: skip
        print(f"action_authority failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("action_authority_gate", main))
