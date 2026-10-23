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
from hooks.scripts.lib.pr_workflow_match import operations, repository, step_found, targets_main, transcript_entries
from hooks.scripts.lib.shell_context import payload_cwd
from scripts.lib import git_common as git
from scripts.lib import merge_target, publication_gate
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
    paths = [
        str(payload[key])
        for key in ("transcript_path", "agent_transcript_path")
        if isinstance(payload.get(key), str) and Path(str(payload[key])).is_file()
    ]
    entries = transcript_entries(paths) if paths else []
    for call in operations(command, payload_cwd(payload)):
        cwd = repository(call)
        if not targets_main(call):
            continue
        name, segment = call.name, call.segment
        number, unit, progress = "", "", ""
        target_number = ""
        if name == "merge":
            if merge_target.has_repo_override(command):
                publication_gate.trace_preflight("pr_repo_override")
                deny("pr_repo_override: Blocked: merge — GH_REPO can retarget publication outside this repository.")
                return 0
            if merge_target.has_base_mutation(command):
                publication_gate.trace_preflight("pr_base_mutation")
                deny("pr_base_mutation: Blocked: merge — edit the PR and re-run the checked merge separately.")
                return 0
            target_number, unit, progress = merge_target.parse(segment)
            try:
                os.chdir(cwd)
                number = merge_target.resolve(target_number)
            except (OSError, ValueError, RuntimeError):
                number = ""
            if not number:
                deny("pr_number_invalid: Blocked: gh pr merge — could not resolve the target PR.")
                return 0
            try:
                head = git.pr_field(number, "headRefOid")
                if not head:
                    raise ValueError("missing head SHA")
                violations = publication_gate.evaluate(number, head, unit, progress)
            except (OSError, ValueError, RuntimeError) as error:
                deny(f"manifest_internal_error: Blocked: merge — publication check failed ({type(error).__name__}).")
                return 0
            if violations:
                first = violations[0]
                deny(f"{first['code']}: Blocked: merge of PR {number} — {first['detail']}")
                return 0
        if not paths or not config_path(cwd):
            continue
        if name == "merge" and not target_number:
            number = ""  # preserve the existing transcript gate's no-target behavior after the publication check
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
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("enforce_pr_workflow", main))
