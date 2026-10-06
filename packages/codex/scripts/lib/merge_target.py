"""Which PR a merge command names: parse `gh pr merge ...`, `gh api .../pulls/N/merge` and merge.py segments.

`parse` skips flag values (`--body 1 42` names 42), keeps URL and branch forms as the target, and marks `-R/--repo`,
two positionals and unparseable quoting as AMBIGUOUS. `resolve` turns a target into a number of THIS repo, or empty
text; an unresolvable target never falls back to the current branch's PR (only "no target given" does, as gh does).
Used by the Claude and Codex direct-merge hooks so both gate the PR that is actually merged.
"""

from __future__ import annotations

import re
import shlex

from . import git_common as git

AMBIGUOUS = "?"
_VALUE_FLAGS = {
    "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit",
    "--unit", "--progress",
}  # fmt: skip
_URL = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)/?$", re.IGNORECASE)


def parse(segment: str) -> tuple[str, str, str]:
    """(target, unit, progress) of one merge segment; target is "" when none, AMBIGUOUS when unresolvable."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return AMBIGUOUS, "", ""
    if tokens[:2] == ["gh", "api"]:
        endpoint = tokens[2] if len(tokens) > 2 else ""
        if api := re.fullmatch(r"/?repos/([^/]+/[^/]+)/pulls/(\d+)/merge", endpoint):
            return f"https://github.com/{api[1]}/pull/{api[2]}", "", ""
        return AMBIGUOUS, "", ""
    start = next((i for i, t in enumerate(tokens) if t == "merge" or re.search(r"(^|/)merge\.(py|sh)$", t)), None)
    if start is None or any(t.startswith("-R") or t.partition("=")[0] == "--repo" for t in tokens[:start]):
        return AMBIGUOUS, "", ""
    script = tokens[start] != "merge"
    positional: list[str] = []
    values: dict[str, str] = {}
    items = iter(tokens[start + 1 :])
    for token in items:
        flag, equals, value = token.partition("=")
        if flag.startswith("-R") or flag == "--repo":
            return AMBIGUOUS, "", ""
        if flag in _VALUE_FLAGS:
            values[flag] = value if equals else next(items, "")
        elif not token.startswith("-"):
            positional.append(token)
    target = positional[0] if len(positional) == 1 else "" if not positional else AMBIGUOUS
    if script and target == "auto":
        target = ""
    return target, values.get("--unit", ""), values.get("--progress", "")


def resolve(target: str) -> str:
    """The PR number for a target in this repo, or "" when it cannot be resolved unambiguously."""
    if target == AMBIGUOUS:
        return ""
    if not target:
        return git.pr_num(git.branch())
    if target.isdigit():
        return target
    if url := _URL.match(target):
        if url[1].lower() != git.repo().lower():
            return ""
    elif "://" in target:
        return ""
    return git.pr_field(target, "number")
