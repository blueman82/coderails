#!/usr/bin/env python3
"""Gate PR and protected-branch operations on native workflow and eval evidence."""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import RESOURCE_MESSAGE, HostResourceError, deny, read_payload_strict
from hooks.scripts.lib.loop_state_common import log
from hooks.scripts.lib.pr_merge_gate import merge_reason
from hooks.scripts.lib.pr_workflow_match import (
    UNBINDABLE,
    Operation,
    operations,
    pr_number,
    repository,
    same_repository,
    step_found,
    targets_main_call,
    transcript_entries,
)
from hooks.scripts.lib.trace_row import append_row

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import git_common as git
from scripts.lib import merge_target, publication_gate
from scripts.lib.authority_permits import permits
from scripts.lib.config import config_path


@contextmanager
def _publication_session(session: str) -> Generator[None, None, None]:
    """Bind publication checks to this hook call only."""
    previous = os.environ.get("CODERAILS_PUBLICATION_SESSION_ID")
    os.environ["CODERAILS_PUBLICATION_SESSION_ID"] = session
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CODERAILS_PUBLICATION_SESSION_ID", None)
        else:
            os.environ["CODERAILS_PUBLICATION_SESSION_ID"] = previous


def _push_changes_repository(calls: list[Operation], cwd: str) -> bool:
    """A protected push with Git root options needs its own binding check."""
    for call in calls:
        if call.name != "git_push":
            continue
        if any(
            token in {"-C", "--git-dir", "--work-tree"} or token.startswith(("-C", "--git-dir=", "--work-tree="))
            for token in call.prefix
        ) and not same_repository(call, cwd):
            return True
    return False


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
    cwd = str(payload.get("cwd") or os.getcwd())
    raw_session = payload.get("session_id")
    session = raw_session if isinstance(raw_session, str) else ""
    calls = operations(command, cwd)
    merges = [call for call in calls if call.name == "merge"]
    guarded = [call for call in calls if call.name == "merge" or (call.name == "git_push" and targets_main_call(call))]
    if len(guarded) > 1:
        deny("Blocked: run one protected action per command so each gets its own review and evidence check.")
        return 0
    if merges and merge_target.has_repo_override(command):
        publication_gate.trace_preflight("pr_repo_override")
        deny("pr_repo_override: GH_REPO can retarget publication outside this repository.")
        return 0
    if guarded and guarded[0].segment.startswith(UNBINDABLE):
        deny("Blocked: child working directory or command target cannot be bound to this repository.")
        return 0
    if _push_changes_repository(guarded, cwd):
        deny("Blocked: Git working directory differs from this repository; run that action separately.")
        return 0
    if merges and not session.strip():
        deny("Blocked: merge publication requires a valid session ID.")
        return 0
    if merges and merge_target.has_base_mutation(command):
        publication_gate.trace_preflight("pr_base_mutation")
        deny("pr_base_mutation: edit the PR and re-run the checked merge separately.")
        return 0
    if merges and not (verdict := permits(session, "merge"))["allow"]:  # early; nothing is consumed
        append_row("action_authority", "denied", f"denied_{verdict['reason']}", session)
        deny(f"Blocked: gh pr merge — this session's authority refuses it ({verdict['reason']}); authority.py inspect.")
        return 0
    paths = [
        str(payload[key])
        for key in ("transcript_path", "agent_transcript_path")
        if isinstance(payload.get(key), str) and Path(str(payload[key])).is_file()
    ]
    configured_calls = [
        call for call in calls if (config_path(repository(call)) or config_path(cwd)) and targets_main_call(call)
    ]
    if configured_calls and not paths:
        name = configured_calls[0].name
        deny("Blocked: protected PR action requires a readable session transcript.")
        log(f"hook=enforce_pr_workflow decision=deny subcommand={name.replace('_', '-')} required=transcript")
        return 0
    entries = transcript_entries(paths)
    for call in merges:
        selected = repository(call)
        requested, unit, progress = merge_target.parse(call.segment)
        previous = os.getcwd()
        try:
            os.chdir(selected)
            number = merge_target.resolve(requested)
            sha = git.pr_field(number, "headRefOid") if number else ""
            if not sha:
                raise ValueError("PR head unavailable")
            with _publication_session(session):
                publication_gate.enforce(number, sha, unit=unit, progress=progress)
        except git.WorkflowError as error:
            deny(str(error))
            return 0
        except (OSError, ValueError, RuntimeError) as error:
            deny(f"Blocked: merge publication check failed: {error}")
            return 0
        finally:
            os.chdir(previous)
    for call in configured_calls:
        selected = repository(call)
        number = merge_target.resolve(pr_number(call.segment)) if call.name == "merge" else ""
        if not step_found(entries, call.name, number):
            required = "/coderails:push" if call.name == "create" else "/pr-review-toolkit:review-pr"
            action = {
                "create": "gh pr create",
                "merge": "gh pr merge",
                "git_merge": "`git merge` on main",
                "git_push": "`git push` on main/master",
            }[call.name]
            deny(f"Blocked: {action} requires {required} to have run this session. Run {required} {number} first.")
            log(f"hook=enforce_pr_workflow decision=deny subcommand={call.name.replace('_', '-')} required={required}")
            return 0
        if call.name == "merge":
            try:
                _, unit, progress = merge_target.parse(call.segment)
                with _publication_session(session):
                    reason = merge_reason(number, selected, session, unit=unit, progress=progress)
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
