"""Which PR a merge command names: parse `gh pr merge ...`, `gh api .../pulls/N/merge` and merge.py segments.

`parse` skips flag values (`--body 1 42` names 42), keeps URL and branch forms as the target, and marks `-R/--repo`,
two positionals and unparseable quoting as AMBIGUOUS. `resolve` turns a target into a number of THIS repo, or empty
text; an unresolvable target never falls back to the current branch's PR (only "no target given" does, as gh does).
Used by the Claude and Codex direct-merge hooks so both gate the PR that is actually merged.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Iterator

from . import git_common as git
from .manifest_policy import unit_flags

AMBIGUOUS = "?"
_VALUE_FLAGS = {
    "-b", "--body", "-F", "--body-file", "-t", "--subject", "-A", "--author-email", "--match-head-commit",
    "--unit", "--progress", "-R", "--repo",
}  # fmt: skip
_URL = re.compile(r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)/?$", re.IGNORECASE)


def has_repo_override(command: str = "") -> bool:
    """A GH_REPO override can retarget gh after the hook has resolved a local PR number."""
    return bool(os.environ.get("GH_REPO") or re.search(r"(?:^|[\s;&|({])(?:export\s+)?GH_REPO\s*=", command))


def has_base_mutation(command: str) -> bool:
    """A same-call PR edit or API update can invalidate the base checked by the hook."""
    if re.search(r"\bgh\s+pr\s+edit(?:\s|$)", command):
        return True
    return any(
        re.search(r"\brepos/[^/\s]+/[^/\s]+/pulls/\d+(?:['\"\s]|$)", api[1])
        for api in re.finditer(r"\bgh\s+api\b([^;&|]*)", command)
    )


def _option_items(tokens: list[str]) -> Iterator[tuple[str, str]]:
    """Yield arguments with their consumed values, using the merge option arities."""
    items = iter(tokens)
    for token in items:
        flag, equals, value = token.partition("=")
        if flag in _VALUE_FLAGS:
            yield flag, value if equals else next(items, "")
        else:
            yield token, ""


def has_noop_option(segment: str) -> bool:
    """Only an actual help/dry-run option makes a command harmless; an option value does not."""
    try:
        return any(token in {"--help", "--dry-run"} for token, _ in _option_items(shlex.split(segment)))
    except ValueError:
        return False


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
    arguments = tokens[start + 1 :]
    unit, progress = "", ""
    if script:
        try:
            arguments, unit, progress = unit_flags(arguments)
        except git.WorkflowError:
            return AMBIGUOUS, "", ""
    positional: list[str] = []
    values: dict[str, str] = {}
    for token, value in _option_items(arguments):
        flag = token.partition("=")[0]
        if flag.startswith("-R") or flag == "--repo":
            return AMBIGUOUS, "", ""
        if flag in _VALUE_FLAGS:
            values[flag] = value
        elif not token.startswith("-"):
            positional.append(token)
    target = positional[0] if len(positional) == 1 else "" if not positional else AMBIGUOUS
    if script and target == "auto":
        target = ""
    return target, unit or values.get("--unit", ""), progress or values.get("--progress", "")


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
