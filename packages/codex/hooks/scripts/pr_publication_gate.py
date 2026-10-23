#!/usr/bin/env python3
"""Codex direct-merge arm of the publication gate (the Codex port of the Claude merge arm, not a second route).

A PreToolUse ^Bash$ hook: every `gh pr merge N`, `gh api .../pulls/N/merge` and merge.py segment (found with the
parity-tested lib/action_match.guarded_segments) is checked with scripts/lib/publication_gate.evaluate on the PR head.
A violation denies with its reason code first; an unresolvable PR or any internal error also denies, never allows.
The check is artifact-based and needs no transcript. Limit: a merge by a script or alias that guarded_segments cannot
see is not covered; scripts/merge.py still enforces the same gate itself. The target is parsed by lib merge_target
(flag values skipped, URL and branch forms resolved through gh, -R/--repo and other-repo URLs denied). Limit: the
hook cannot pin the head, so a push between this check and the agent's own `gh pr merge` is not caught there
(merge.py pins it with --match-head-commit).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import cast

from hook_common import deny, payload_object, read_input, text_field
from lib.action_match import guarded_segments

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import merge_target, publication_gate  # noqa: E402


def main() -> int:
    """Check one Bash payload; deny on a violation, on an unresolvable PR and on any internal error."""
    payload = payload_object(read_input())
    data = payload.get("tool_input")
    command = cast(dict[str, object], data).get("command") if isinstance(data, dict) else None
    if not isinstance(command, str) or "merge" not in command:
        return 0
    session = payload.get("session_id")
    if isinstance(session, str) and session:
        os.environ["CODERAILS_PUBLICATION_SESSION_ID"] = session
    cwd = text_field(payload, "cwd") or os.getcwd()
    try:
        for name, segment, where in guarded_segments(command, cwd):
            if name != "merge":
                continue
            if merge_target.has_repo_override(command):
                publication_gate.trace_preflight("pr_repo_override")
                deny("pr_repo_override: Blocked: merge — GH_REPO can retarget publication outside this repository.")
                return 0
            if merge_target.has_base_mutation(command):
                publication_gate.trace_preflight("pr_base_mutation")
                deny("pr_base_mutation: Blocked: merge — edit the PR and re-run the checked merge separately.")
                return 0
            os.chdir(where)
            target, unit, progress = merge_target.parse(segment)
            number = merge_target.resolve(target)
            if not number:
                deny("pr_number_invalid: Blocked: merge — could not resolve a PR number for the publication gate.")
                return 0
            if violations := publication_gate.evaluate(number, git.pr_field(number, "headRefOid"), unit, progress):
                first = violations[0]
                deny(
                    f"{first['code']}: Blocked: merge of PR {number} — the publication gate refused this head "
                    f"({first['detail'] or 'no detail'}). Fix the diff or the policy; diff_manifest: off is the switch."
                )
                return 0
    except Exception as error:  # noqa: BLE001 - fail closed: an erroring gate must not allow a merge
        deny(f"manifest_internal_error: Blocked: merge — publication gate failed ({type(error).__name__}).")
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("pr_publication_gate", main))
