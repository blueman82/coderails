#!/usr/bin/env python3
"""Action-receipt gate: shipped advisory mode warns (Codex copy of hooks/scripts/action_authority_gate.py).

Config `action_authority`: advisory | enforce | off; absent or unknown config is off.
Advisory warns on missing receipts; live authority denials and
unbindable merges under a live merge cap still block.
Enforce denies unless
authority.permits() allows and a receipt verifies (mirrored scripts/lib/receipt_gate.py, shared with merge.py, which is
independently fail-closed); any own error fails open (action_authority_failed_open). Receipts are signed and bound to
repository+ref+sha; with the user-tier trust root that is a cooperating-agent safeguard, not a boundary. The hash
covers only the command text seen here.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, cast

from hook_common import append_trace_row, deny, payload_object, read_input, text_field
from lib.action_match import MERGE_SCRIPT, guarded_segments, state_mutated_before_guard
from lib.destructive_patterns import git_output

from scripts.lib import advisory_merge, merge_budget
from scripts.lib.action_binding import binding, merge_number
from scripts.lib.action_receipt import proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.receipt_gate import check_and_consume, resolve_mode
from scripts.lib.receipt_signing import USER_TIER, resolve_trust_root


def mode(cwd: str) -> str:
    """Return advisory, enforce or off, never raising."""
    return resolve_mode(cwd)[0]


def proposal(name: str, segment: str, where: str) -> tuple[str, dict[str, Any]]:
    """The action as seen here, plus the PR number of a merge.py segment (merge.py matches on it)."""
    branch = git_output(where, "branch", "--show-current")
    proposed = proposed_action(name, segment, where, branch, binding(name, segment, where))
    script = name == "merge" and bool(re.search(MERGE_SCRIPT, segment))
    return name, proposed | {"script": script, "number": merge_number(segment, where) if name == "merge" else ""}


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
        "For optional receipt enforcement, sign one at a terminal with the configured key: run "
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
        mode_, _ = resolve_mode(cwd)
        if mode_ == "off" or not (segments := guarded_segments(command, cwd, implicit_push=True)):
            return 0
        authority = read_authority(session) or {}
        loop_id = authority.get("loop_id")
        loop = loop_id if isinstance(loop_id, str) else None
        signers, tier = resolve_trust_root()

        def claimed(_name: str) -> None:
            if tier == USER_TIER:
                append_trace_row("action_authority", "allowed", USER_TIER, trace_id, {"loop_id": loop})
            append_trace_row("action_authority", "allowed", "receipt_consumed", trace_id, {"loop_id": loop})

        proposals = [proposal(*segment) for segment in segments]
        missing = check_and_consume(
            session, proposals, None, loop, signers,
            consume=mode_ == "enforce", stale=state_mutated_before_guard(command), on_claim=claimed,
        )  # fmt: skip
        denied_by_authority = missing is not None and missing[1] in {"authority_denied", "max_prs_exceeded"}
        reservation_failed = False
        if mode_ == "advisory" and authority and not denied_by_authority:
            reserved: list[Path] = []
            for name, item in proposals:
                if name != "merge" or item["script"]:
                    continue
                bind = {"repository": item["repository"], "ref": item["ref"], "sha": item["artifact_sha"]}
                code, path = advisory_merge.reserve(session, item["number"], bind)
                if code != "ok":
                    for previous in reserved:
                        merge_budget.settle(previous, False)
                    missing = (name, code)
                    reservation_failed = True
                    break
                if path:
                    reserved.append(path)
        if missing is None:
            return 0
        name, code = missing
        if mode_ == "advisory" and not reservation_failed and code not in {"authority_denied", "max_prs_exceeded"}:
            append_trace_row("action_authority", "advisory", f"advisory_{code}", trace_id, {"loop_id": loop})
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_trace_row("action_authority", "denied", f"denied_{code}", trace_id, {"loop_id": loop})
        need = "needs a bound PR and head under live authority" if reservation_failed else "needs an action receipt"
        deny(f"Blocked: {name.replace('_', ' ')} {need} ({code}). {how_to_proceed(code, session, name)}")
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
