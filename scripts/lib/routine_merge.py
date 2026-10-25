"""Pin one routine merge attempt to its exact GitHub PR and inspect its live state."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from typing import Any, cast

from . import git_common as git
from . import merge_target


def status(attempt: object) -> str:
    """Return OPEN or MERGED only for the pinned PR and head; otherwise UNKNOWN."""
    if not isinstance(attempt, dict):
        return "UNKNOWN"
    pinned = cast(dict[str, Any], attempt)
    done = git.run(
        "gh", "pr", "view", str(pinned.get("number", "")), "--json", "number,url,headRefName,headRefOid,state"
    )
    try:
        pr = cast(dict[str, Any], json.loads(done.stdout))
        keys = ("number", "url", "headRefName", "headRefOid")
        if done.returncode or any(pr.get(key) != pinned.get(key) for key in keys):
            return "UNKNOWN"
        return str(pr["state"]) if pr["state"] in ("OPEN", "MERGED") else "UNKNOWN"
    except (ValueError, KeyError, TypeError):
        return "UNKNOWN"


def cleanup_numbers(branch: str, attempt: object) -> list[str]:
    """Close only the pinned PR after a merge attempt; otherwise use the branch's open PRs."""
    if isinstance(attempt, dict):
        number = cast(dict[str, Any], attempt).get("number")
        return [str(number)] if isinstance(number, int) else []
    listing = ("gh", "pr", "list", "--head", branch, "--state", "open")
    return git.run(*listing, "--json", "number", "--jq", ".[].number").stdout.split()


def scope_attempt(
    argv: list[str], expected_branch: str, check_manifest: Callable[[str, str], str]
) -> tuple[str, dict[str, Any]]:
    """Validate the exact OPEN PR, branch, head and manifest before the merge command."""
    target, _, _ = merge_target.parse(shlex.join(argv))
    branch, head = git.branch(), git.output("git", "rev-parse", "HEAD")
    if not target.isdecimal() or not branch or branch != expected_branch or not head:
        return "gate_argv_not_allowed", {}
    done = git.run("gh", "pr", "view", target, "--json", "number,url,headRefName,headRefOid,baseRefOid,state")
    try:
        pr = cast(dict[str, Any], json.loads(done.stdout))
        base = pr["baseRefOid"]
        url = str(pr["url"])
        expected_repo = git.repo()
        if (
            done.returncode
            or pr["number"] != int(target)
            or not re.fullmatch(rf"https://github\.com/[^/]+/[^/]+/pull/{target}", url)
            or (expected_repo and url != f"https://github.com/{expected_repo}/pull/{target}")
            or pr["headRefName"] != branch
            or pr["headRefOid"] != head
            or pr["state"] != "OPEN"
            or not isinstance(base, str)
            or not re.fullmatch(r"[0-9a-fA-F]{40}", base)
        ):
            return "gate_argv_not_allowed", {}
    except (ValueError, KeyError, TypeError):
        return "gate_argv_not_allowed", {}
    code = check_manifest(base, head)
    return code, {} if code else {key: pr[key] for key in ("number", "url", "headRefName", "headRefOid")}
