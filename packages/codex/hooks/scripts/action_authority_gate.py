#!/usr/bin/env python3
"""Action-receipt gate: shipped advisory mode warns (Codex copy of hooks/scripts/action_authority_gate.py).

Config `action_authority`: advisory | enforce | off; absent or unknown config is off.
Advisory warns on missing receipts; live authority denials and
unbindable merges under a live merge cap still block.
Enforce denies unless
authority.permits() allows and a receipt verifies (mirrored scripts/lib/receipt_gate.py, shared with merge.py, which is
independently fail-closed); unexpected errors deny under enforce or live authority. Receipts are signed and bound to
repository+ref+sha; with the user-tier trust root that is a cooperating-agent safeguard, not a boundary. The hash
covers only the command text seen here.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from hook_common import append_trace_row, deny, payload_object, read_input, text_field
from lib.action_match import MERGE_SCRIPT, Operation, guarded_operations, repository, state_mutated_before_guard
from lib.destructive_patterns import git_output

from scripts.lib import advisory_merge, merge_budget
from scripts.lib.action_binding import binding, merge_number
from scripts.lib.action_receipt import proposed_action
from scripts.lib.authority_object import read_authority
from scripts.lib.config import config_path
from scripts.lib.config_strict import ConfigRejected, strict_settings
from scripts.lib.receipt_gate import check_and_consume, resolve_mode
from scripts.lib.receipt_signing import USER_TIER, resolve_trust_root


def mode(cwd: str) -> str:
    """Return advisory, enforce or off, never raising."""
    return resolve_mode(cwd)[0]


def proposal(call: Operation) -> tuple[str, dict[str, Any]]:
    """The action as seen here, plus the PR number of a merge.py segment (merge.py matches on it)."""
    branch = git_output(call.git_cwd, *call.prefix, "branch", "--show-current")
    proposed = proposed_action(call.name, call.segment, call.cwd, branch, binding(call.name, call.segment, call.cwd))
    script = call.name == "merge" and bool(re.search(MERGE_SCRIPT, call.segment))
    return call.name, proposed | {
        "script": script,
        "number": merge_number(call.segment, call.cwd) if call.name == "merge" else "",
    }


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


def check_action_modes(
    session: str, active: list[tuple[Operation, str]], command: str, loop: str | None,
    signers: Path | None, authority: bool, claimed: Callable[[str], None],
) -> tuple[tuple[str, str] | None, bool]:  # fmt: skip
    """Check the whole command before claiming enforce receipts; advisory receipts stay unused."""
    proposals = [(mode, proposal(call)) for call, mode in active]
    all_actions = [item for _, item in proposals]
    stale = state_mutated_before_guard(command)
    whole = check_and_consume(session, all_actions, None, loop, signers, consume=False, stale=stale)
    hard = {"authority_denied", "max_prs_exceeded", "approval_requirement_missing", "budget_lock_unavailable"}
    if whole is not None and whole[1] in hard:
        return whole, True
    advisory = [item for mode, item in proposals if mode == "advisory"]
    enforce = [item for mode, item in proposals if mode == "enforce"]
    advisory_missing = (
        check_and_consume(session, advisory, None, loop, signers, consume=False, stale=stale) if advisory else None
    )
    if advisory_missing is not None and advisory_missing[1] in hard:
        return advisory_missing, True
    if enforce:
        missing = check_and_consume(session, enforce, None, loop, signers, consume=False, stale=stale)
        if missing is not None:
            return missing, True
    reserved: list[Path] = []
    if authority:
        for name, item in advisory:
            if name != "merge" or item["script"]:
                continue
            bind = {"repository": item["repository"], "ref": item["ref"], "sha": item["artifact_sha"]}
            code, path = advisory_merge.reserve(session, item["number"], bind)
            if code != "ok":
                for previous in reserved:
                    try:
                        merge_budget.settle(previous, False)
                    except OSError:
                        code = "budget_release_failed"
                return (name, code), True
            if path:
                reserved.append(path)
    if enforce:
        missing = check_and_consume(session, enforce, None, loop, signers, stale=stale, on_claim=claimed)
        if missing is not None:
            for previous in reserved:
                merge_budget.settle(previous, False)
            return missing, True
    return advisory_missing, False


def main() -> int:
    """Check one Bash payload; deny unexpected errors under enforce or live authority."""
    payload = payload_object(read_input())
    session = text_field(payload, "session_id")
    trace_id = session or "_no_session"
    loop: str | None = None
    mode_ = "off"
    authority: dict[str, Any] = {}
    try:
        data = payload.get("tool_input")
        command = cast(dict[str, object], data).get("command") if isinstance(data, dict) else None
        cwd = text_field(payload, "cwd") or os.getcwd()
        if not isinstance(command, str) or not command:
            return 0
        if not (calls := guarded_operations(command, cwd, implicit_push=True)):
            return 0
        source_mode, _ = resolve_mode(cwd)
        priority = {"off": 0, "advisory": 1, "enforce": 2}
        configured: list[tuple[Operation, str]] = []
        for call in calls:
            selected = repository(call)
            config = config_path(selected)
            selected_mode, _ = resolve_mode(selected)
            selected_mode = max((source_mode, selected_mode), key=priority.__getitem__)
            configured.append((call, selected_mode))
            if not config:
                continue
            try:
                strict_settings(config, session)
            except ConfigRejected as error:
                append_trace_row("action_authority", "denied", "config_rejected", trace_id, {})
                deny(
                    f"Blocked: {call.name.replace('_', ' ')} while the workflow config is invalid. {error}. "
                    "Fix .coderails/workflow.config.yaml (scripts/lib/config.py resolve-config --json lists "
                    "the findings)."
                )
                return 0
        active = [(call, selected_mode) for call, selected_mode in configured if selected_mode != "off"]
        if not active:
            return 0
        mode_ = "enforce" if any(selected_mode == "enforce" for _, selected_mode in active) else "advisory"
        authority = read_authority(session) or {}
        loop_id = authority.get("loop_id")
        loop = loop_id if isinstance(loop_id, str) else None
        signers, tier = resolve_trust_root()

        def claimed(_name: str) -> None:
            if tier == USER_TIER:
                append_trace_row("action_authority", "allowed", USER_TIER, trace_id, {"loop_id": loop})
            append_trace_row("action_authority", "allowed", "receipt_consumed", trace_id, {"loop_id": loop})

        missing, blocked = check_action_modes(session, active, command, loop, signers, bool(authority), claimed)
        if missing is None:
            return 0
        name, code = missing
        if not blocked:
            append_trace_row("action_authority", "advisory", f"advisory_{code}", trace_id, {"loop_id": loop})
            print(f"action_authority (advisory): no valid receipt for {name} ({code}); not blocked.", file=sys.stderr)
            return 0
        append_trace_row("action_authority", "denied", f"denied_{code}", trace_id, {"loop_id": loop})
        need = "needs a bound PR and head" if code.startswith("budget_") else "needs an action receipt"
        deny(f"Blocked: {name.replace('_', ' ')} {need} ({code}). {how_to_proceed(code, session, name)}")
    except Exception as error:  # noqa: BLE001 - live authority must refuse unexpected hook errors
        if mode_ == "enforce" or authority:
            deny(f"Blocked: action authority gate error ({type(error).__name__}).")
            with suppress(Exception):  # trace is not required to deny the command
                append_trace_row("action_authority", "denied", "denied_gate_error", trace_id, {"loop_id": loop})
        else:
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
