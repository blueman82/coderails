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
from hooks.scripts.lib.pr_workflow_match import (
    guarded_segments,
    operation,
    pr_number,
    step_found,
    targets_main,
    transcript_entries,
)
from hooks.scripts.lib.trace_row import append_row

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import git_common as git
from scripts.lib import merge_target, publication_gate
from scripts.lib.authority_permits import permits
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
    session = str(payload.get("session_id") or "")
    merges = [(part, where) for kind, part, where in guarded_segments(command, cwd) if kind == "merge"]
    if merges:
        name, segment, cwd = "merge", merges[0][0], merges[0][1]
    if merges and not (verdict := permits(session, "merge"))["allow"]:  # early; nothing is consumed
        append_row("action_authority", "denied", f"denied_{verdict['reason']}", session)
        deny(f"Blocked: gh pr merge — this session's authority refuses it ({verdict['reason']}); authority.py inspect.")
        return 0
    if merges and merge_target.has_repo_override(command):
        publication_gate.trace_preflight("pr_repo_override")
        deny("pr_repo_override: GH_REPO can retarget publication outside this repository.")
        return 0
    if merges and merge_target.has_base_mutation(command):
        publication_gate.trace_preflight("pr_base_mutation")
        deny("pr_base_mutation: edit the PR and re-run the checked merge separately.")
        return 0
    configured = bool(name and config_path(cwd) and targets_main(command, cwd, target, name))
    paths = [
        str(payload[key])
        for key in ("transcript_path", "agent_transcript_path")
        if isinstance(payload.get(key), str) and Path(str(payload[key])).is_file()
    ]
    if configured and not paths:
        deny("Blocked: protected PR action requires a readable session transcript.")
        log(f"hook=enforce_pr_workflow decision=deny subcommand={name.replace('_', '-')} required=transcript")
        return 0
    for part, where in merges:
        requested, unit, progress = merge_target.parse(part)
        try:
            os.chdir(where)
            number = merge_target.resolve(requested)
            sha = git.pr_field(number, "headRefOid") if number else ""
            if not sha:
                raise ValueError("PR head unavailable")
            publication_gate.enforce(number, sha, unit=unit, progress=progress)
        except git.WorkflowError as error:
            deny(str(error))
            return 0
        except (OSError, ValueError, RuntimeError) as error:
            deny(f"Blocked: merge publication check failed: {error}")
            return 0
    if not configured:
        return 0
    number = merge_target.resolve(pr_number(segment)) if name == "merge" else ""
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
            _, unit, progress = merge_target.parse(segment)
            reason = merge_reason(number, cwd, session, unit=unit, progress=progress)
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
