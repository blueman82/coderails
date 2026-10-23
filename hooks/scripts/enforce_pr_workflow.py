#!/usr/bin/env python3
"""Gate PR and protected-branch operations on native workflow and eval evidence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import RESOURCE_MESSAGE, HostResourceError, deny, read_payload_strict
from hooks.scripts.lib.loop_state_common import log
from hooks.scripts.lib.pr_merge_gate import merge_reason
from hooks.scripts.lib.pr_workflow_match import operation, pr_number, step_found, targets_main, transcript_entries

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib.config import config_path


def main() -> int:
    """Redirect missing workflow steps and fail closed on live merge evidence failure."""
    try:
        payload = read_payload_strict()
    except HostResourceError:
        deny(RESOURCE_MESSAGE)  # fail closed: a gate that cannot read its input must not allow the action
        return 0
    data = payload.get("tool_input")
    command = data.get("command") if isinstance(data, dict) else None
    if not isinstance(command, str) or not command:
        return 0
    name, segment, target = operation(command)
    cwd = str(payload.get("cwd") or os.getcwd())
    if not name or not config_path(cwd) or not targets_main(command, cwd, target, name):
        return 0
    paths = [
        str(payload[key])
        for key in ("transcript_path", "agent_transcript_path")
        if isinstance(payload.get(key), str) and Path(str(payload[key])).is_file()
    ]
    if not paths:
        return 0
    number = pr_number(segment) if name == "merge" else ""
    if not step_found(transcript_entries(paths), name, number):
        required = "/coderails:push" if name == "create" else "/pr-review-toolkit:review-pr"
        action = {
            "create": "gh pr create",
            "merge": "gh pr merge",
            "git_merge": "`git merge` on main",
            "git_push": "`git push` on main/master",
        }[name]
        deny(f"Blocked: {action} requires {required} to have run this session. Run {required} {number} first.")
        log(f"hook=enforce_pr_workflow decision=deny subcommand={name.replace('_', '-')} required={required}")
        return 0
    if name == "merge":
        try:
            reason = merge_reason(number, cwd)
        except (OSError, ValueError, RuntimeError) as error:
            reason = f"Blocked: gh pr merge — eval artifact verification failed: {error}. Do not bypass."
        if reason:
            deny(reason)
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("enforce_pr_workflow", main))
