#!/usr/bin/env python3
"""Codex direct-merge arm of the publication gate (the Codex port of the Claude merge arm, not a second route).

A PreToolUse ^Bash$ hook: every `gh pr merge N`, `gh api .../pulls/N/merge` and merge.py segment (found with the
parity-tested lib/action_match.guarded_segments) is checked with scripts/lib/publication_gate.evaluate on the PR head.
A violation denies with its reason code first; an unresolvable PR or any internal error also denies, never allows.
The check is artifact-based and needs no transcript. Limit: a merge by a script or alias that guarded_segments cannot
see is not covered; scripts/merge.py still enforces the same gate itself.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import cast

from hook_common import deny, payload_object, read_input, text_field
from lib.action_match import guarded_segments

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import publication_gate  # noqa: E402


def pr_number(segment: str) -> str:
    """The PR number named in a merge segment, or empty text."""
    if match := re.search(r"/pulls/(\d+)/merge", segment):
        return match[1]
    tokens = segment.split()
    start = next((i for i, token in enumerate(tokens) if re.search(r"merge(\.py|\.sh)?[\"']?$", token)), len(tokens))
    return next((t.strip("\"'") for t in tokens[start + 1 :] if re.fullmatch(r"[\"']?\d+[\"']?", t)), "")


def main() -> int:
    """Check one Bash payload; deny on a violation, on an unresolvable PR and on any internal error."""
    payload = payload_object(read_input())
    data = payload.get("tool_input")
    command = cast(dict[str, object], data).get("command") if isinstance(data, dict) else None
    if not isinstance(command, str) or "merge" not in command:
        return 0
    cwd = text_field(payload, "cwd") or os.getcwd()
    try:
        for name, segment, where in guarded_segments(command, cwd):
            if name != "merge":
                continue
            os.chdir(where)
            number = pr_number(segment) or git.pr_num(git.branch())
            if not number:
                deny("pr_number_invalid: Blocked: merge — could not resolve a PR number for the publication gate.")
                return 0
            if violations := publication_gate.evaluate(number, git.pr_field(number, "headRefOid")):
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
    raise SystemExit(main())
