"""Verify durable wiki coverage for merged PRs after the configured epoch."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from . import git_common as git
from .config import config_path, settings


def covered(vault: Path, ref: str, repository: str, number: int) -> bool:
    """Match the shared no-op ledger and source-origin coverage patterns."""
    escaped = re.escape(repository)
    patterns = (
        (rf"^## \[[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}\] no-op \| {escaped} PR #{number}([^0-9]|$)", "log.md"),
        (rf"^origin:(.*[^A-Za-z0-9._-])?{escaped} PRs? [^\"]*#{number}([^0-9]|$)", "sources/"),
    )
    return any(
        git.run("git", "-C", str(vault), "grep", "-qE", pattern, ref, "--", path).returncode == 0
        for pattern, path in patterns
    )


def merged_candidates(number: str, epoch: int) -> list[int]:
    """Read a complete bounded merged-PR window or fail closed."""
    response = git.run("gh", "pr", "list", "--state", "merged", "--json", "number", "--limit", "100")
    if response.returncode:
        raise git.WorkflowError("GitHub fetch failed for the wiki-ingest merged-PR list")
    text = response.stdout.strip()
    if not text:
        raise git.WorkflowError("Wiki-ingest debt gate received an empty merged-PR response")
    try:
        values: object = json.loads(text)
        if not isinstance(values, list):
            raise ValueError("expected an array")
        entries = cast(list[dict[str, Any]], values)
        if len(entries) >= 100:
            raise git.WorkflowError("merged-PR window full — advance wiki_debt_epoch_pr or raise the limit")
        return [
            int(entry["number"]) for entry in entries if int(entry["number"]) > epoch and str(entry["number"]) != number
        ]
    except (ValueError, TypeError, KeyError) as error:
        raise git.WorkflowError("Could not parse the merged PR list for the wiki-ingest debt gate") from error


def open_coverage(vault: Path, repository: str, remaining: list[int]) -> list[int]:
    """Accept coverage in open vault PRs while refusing unresolved fetch failures."""
    vault_repo = git.repo_from_url(git.output("git", "-C", str(vault), "remote", "get-url", "origin"))
    if not vault_repo:
        print("! Wiki-ingest debt: in-progress-coverage probe skipped (vault origin is not a github.com URL)")
        return remaining
    response = git.run(
        "gh",
        "pr",
        "list",
        "--repo",
        vault_repo,
        "--state",
        "open",
        "--json",
        "headRefName",
        "--limit",
        "100",
        "-q",
        ".[].headRefName",
    )
    if response.returncode:
        raise git.WorkflowError("GitHub fetch failed for the open wiki PR list")
    heads = response.stdout.splitlines()
    if len(heads) >= 100:
        print(f"! Wiki-ingest debt: vault {vault_repo} has 100+ open PRs — in-progress coverage may be incomplete")
    failed: list[str] = []
    for head in heads:
        if not head or not remaining:
            continue
        if git.run("git", "-C", str(vault), "fetch", "-q", "origin", head).returncode:
            failed.append(head)
            continue
        pending = [number for number in remaining if covered(vault, "FETCH_HEAD", repository, number)]
        if pending:
            print(f"! Wiki-ingest debt coverage in progress (open vault PR): {pending} (vault:{head})")
        remaining = [number for number in remaining if number not in pending]
    if failed:
        print(f"! Wiki-ingest debt: could not fetch open vault PR heads: {', '.join(failed)}")
        if remaining:
            raise git.WorkflowError(f"could not verify in-progress coverage for {remaining}: fetch failed for {failed}")
    return remaining


def has_wiki_ingest_for_merged_prs(number: str) -> None:
    """Refuse configured wiki debt, treating configuration absence as inert."""
    config = config_path()
    if config:
        try:
            Path(config).read_text(encoding="utf-8")
        except OSError as error:
            raise git.WorkflowError("Could not read wiki-ingest debt configuration") from error
    values = settings(config) if config else {}
    epoch = "" if values.get("wiki_debt_epoch_pr") is None else str(values["wiki_debt_epoch_pr"])
    relative = values.get("wiki_path") or ""
    if not epoch or not relative:
        print("• Wiki-ingest debt gate skipped — wiki_debt_epoch_pr and/or wiki_path not configured")
        return
    if not re.fullmatch(r"[0-9]+", epoch):
        raise git.WorkflowError(f"wiki_debt_epoch_pr ('{epoch}') is not a PR number")
    vault = (Path(config).parent.parent / relative).resolve()
    if not vault.is_dir():
        raise git.WorkflowError(f"wiki_path ('{relative}') does not resolve to a directory")
    repository = git.repo().rsplit("/", 1)[-1]
    if not repository:
        raise git.WorkflowError("Could not resolve the origin repo for the wiki-ingest debt gate")
    candidates = merged_candidates(number, int(epoch))
    if not candidates:
        print(f"✓ Wiki-ingest debt clear (no merged PRs after epoch #{epoch})")
        return
    if git.run("git", "-C", str(vault), "fetch", "-q", "origin", "main").returncode:
        raise git.WorkflowError("Wiki fetch failed for origin/main")
    if git.run("git", "-C", str(vault), "rev-parse", "-q", "--verify", "origin/main").returncode:
        raise git.WorkflowError("Wiki has no origin/main ref after fetch")
    remaining = [candidate for candidate in candidates if not covered(vault, "origin/main", repository, candidate)]
    if remaining:
        remaining = open_coverage(vault, repository, remaining)
    if remaining:
        missing = ", ".join(f"#{candidate}" for candidate in remaining)
        raise git.WorkflowError(
            f"Wiki-ingest debt: merged {repository} PR(s) not covered in the wiki: {missing}. "
            "Run wiki-ingest or record a canonical no-op ledger entry."
        )
    print(f"✓ Wiki-ingest debt clear (epoch #{epoch})")
