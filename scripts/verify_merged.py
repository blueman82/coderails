#!/usr/bin/env python3
"""Confirm a PR really landed: `verify_merged.py <PR> [--grep STR --path P] [--repo DIR]` prints a JSON verdict.

One rule set for merge commits and squash merges: state MERGED plus mergedAt; fetch the base; the mergeCommit is
reachable from origin/<base>; then content (`git grep` finds the needle at the merge commit and current base tip,
but not at the merge commit's first parent, so it is unique to the change; a pre-existing string is refused).
Ancestry of the PR head is trusted only for a true merge commit (two parents) and only when no content check was
given; a squash rewrites the SHA, so it is never required of one.
Exit 0 when confirmed, 1 otherwise. `method` is `content` or `merge-commit-ancestry`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import cast


def run(repo: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """Run a command in the repo, capturing output; spawn failure is a nonzero result."""
    try:
        return subprocess.run(argv, cwd=repo, capture_output=True, text=True, check=False)
    except OSError as error:
        return subprocess.CompletedProcess(argv, 127, "", str(error))


def pr_facts(repo: Path, number: str, origin_repo: str) -> dict[str, object] | None:
    """`gh pr view` fields as a dict, or None when gh fails or returns something unusable."""
    result = run(
        repo,
        "gh",
        "pr",
        "view",
        number,
        "--repo",
        f"github.com/{origin_repo}",
        "--json",
        "state,mergedAt,mergeCommit,baseRefName,headRefOid",
    )
    try:
        data: object = json.loads(result.stdout)
    except ValueError:
        return None
    return cast("dict[str, object]", data) if result.returncode == 0 and isinstance(data, dict) else None


def verify(repo: Path, number: str, needle: str, path: str) -> dict[str, object]:
    """Apply the rule set and return the verdict."""
    verdict: dict[str, object] = {"pr": number, "confirmed": False, "method": "", "reasons": []}
    reasons: list[str] = verdict["reasons"]  # type: ignore[assignment]
    if not number.isascii() or not number.isdecimal() or not number.strip("0"):
        reasons.append("pr_number_invalid")
        return verdict
    origin_url = run(repo, "git", "config", "--get", "remote.origin.url").stdout.strip()
    match = re.fullmatch(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)",
        origin_url,
    )
    origin_repo = match.group(1).removesuffix(".git") if match else ""
    if not origin_repo:
        reasons.append("origin_repo_unresolved")
        return verdict
    if os.environ.get("GH_REPO") and os.environ["GH_REPO"] != origin_repo:
        reasons.append("repo_mismatch")
        return verdict
    facts = pr_facts(repo, number, origin_repo)
    if facts is None:
        reasons.append("gh_failed")
        return verdict
    commit = facts.get("mergeCommit")
    oid = str(cast("dict[str, object]", commit).get("oid") or "") if isinstance(commit, dict) else ""
    base = str(facts.get("baseRefName") or "")
    head = str(facts.get("headRefOid") or "")
    verdict.update(state=facts.get("state"), merged_at=facts.get("mergedAt"), merge_commit=oid, base=base)
    if facts.get("state") != "MERGED":
        reasons.append("not_merged")
    if not facts.get("mergedAt"):
        reasons.append("merged_at_missing")
    if reasons:
        return verdict
    if not base or run(repo, "git", "fetch", "origin", base, "--quiet").returncode:
        reasons.append("fetch_failed")
        return verdict
    tip = f"origin/{base}"
    if not oid or run(repo, "git", "merge-base", "--is-ancestor", oid, tip).returncode:
        reasons.append("merge_commit_unreachable")
        return verdict
    parents = run(repo, "git", "rev-list", "--parents", "-n", "1", oid).stdout.split()[1:]
    verdict["parents"] = len(parents)
    if needle:
        found = run(repo, "git", "grep", "-q", "-F", "-e", needle, oid, *(["--", path] if path else []))
        current = run(repo, "git", "grep", "-q", "-F", "-e", needle, tip, *(["--", path] if path else []))
        verdict["content_found"] = found.returncode == 0 and current.returncode == 0
        # the needle must be new in this PR: present at the base parent means it proves nothing about the change
        before = run(repo, "git", "grep", "-q", "-F", "-e", needle, f"{oid}^1", *(["--", path] if path else []))
        if found.returncode not in (0, 1) or current.returncode not in (0, 1) or before.returncode not in (0, 1):
            reasons.append("content_check_failed")
        elif found.returncode == 0 and current.returncode == 0 and before.returncode == 0:
            reasons.append("content_preexisting")
        elif found.returncode == 0 and current.returncode == 0:
            verdict.update(confirmed=True, method="content")
        else:
            reasons.append("content_absent")
    elif len(parents) == 2 and head and run(repo, "git", "merge-base", "--is-ancestor", head, oid).returncode == 0:
        verdict.update(confirmed=True, method="merge-commit-ancestry")
    else:
        reasons.append("content_check_required")
    return verdict


def trace(repo: Path, verdict: dict[str, object]) -> None:
    """One non-authoritative `verify-merged/<ok|refused>/<reason>` row (both packages ship lib/trace_row)."""
    reasons: list[str] = verdict["reasons"]  # type: ignore[assignment]
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        append_row = importlib.import_module("hooks.scripts.lib.trace_row").append_row
        label = re.sub(r"[^A-Za-z0-9_.@-]", "_", f"{repo.name}@pr-{verdict['pr']}")
        append_row("verify-merged", "refused" if reasons else "ok", reasons[0] if reasons else "verified", label)
    except Exception:  # noqa: BLE001 - a trace row never decides anything
        return


def main(argv: list[str] | None = None) -> int:
    """CLI entry."""
    arguments = sys.argv[1:] if argv is None else argv
    if (
        arguments
        and arguments[0].startswith("-")
        and arguments[0] not in ("-h", "--help", "--grep", "--path", "--repo", "--")
    ):
        verdict = verify(Path.cwd(), arguments[0], "", "")
        print(json.dumps(verdict, indent=2))
        return 1
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pr")
    parser.add_argument(
        "--grep",
        default="",
        help="string unique to the change: present at origin/<base>, absent at the merge commit's first parent",
    )
    parser.add_argument("--path", default="", help="limit the grep to this path")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(arguments)
    verdict = verify(args.repo.resolve(), args.pr, args.grep, args.path)
    trace(args.repo.resolve(), verdict)
    print(json.dumps(verdict, indent=2))
    return 0 if verdict["confirmed"] else 1


if __name__ == "__main__":
    sys.exit(main())
