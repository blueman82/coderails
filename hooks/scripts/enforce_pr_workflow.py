#!/usr/bin/env python3
"""Gate PR and protected-branch operations on native workflow and eval evidence."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.loop_state_common import log
from hooks.scripts.lib.pr_merge_gate import merge_reason
from hooks.scripts.lib.pr_workflow_match import operations, repository, step_found, targets_main, transcript_entries
from hooks.scripts.lib.shell_context import payload_cwd
from scripts.lib import merge_target
from scripts.lib.config import config_path


def main() -> int:
    """Redirect missing workflow steps and fail closed on live merge evidence failure."""
    payload = read_payload()
    data = payload.get("tool_input")
    command = data.get("command") if isinstance(data, dict) else None
    if not isinstance(command, str) or not command:
        return 0
    paths = [
        str(payload[key])
        for key in ("transcript_path", "agent_transcript_path")
        if isinstance(payload.get(key), str) and Path(str(payload[key])).is_file()
    ]
    if not paths:
        return 0
    entries = transcript_entries(paths)
    for call in operations(command, payload_cwd(payload)):
        cwd = repository(call)
        if not config_path(cwd) or not targets_main(call):
            continue
        name, segment = call.name, call.segment
        number, unit, progress = merge_target.parse(segment) if name == "merge" else ("", "", "")
        if name == "merge" and number:
            try:
                os.chdir(cwd)
                number = merge_target.resolve(number)
            except (OSError, ValueError, RuntimeError):
                number = ""
            if not number:
                deny("pr_number_invalid: Blocked: gh pr merge — could not resolve the target PR.")
                return 0
        if not step_found(entries, name, number):
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
                reason = merge_reason(number, cwd, unit=unit, progress=progress)
            except (OSError, ValueError, RuntimeError) as error:
                reason = f"Blocked: gh pr merge — eval artifact verification failed: {error}. Do not bypass."
            if reason:
                deny(reason)
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
