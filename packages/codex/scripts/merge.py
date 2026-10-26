#!/usr/bin/env python3
"""Verify exact-head review, eval, integrity and wiki evidence before merging."""

from __future__ import annotations

import json
import re
import shlex
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import git_common as git
from scripts.lib import manifest_policy, merge_budget, merge_target, publication_gate
from scripts.lib.config import config_path, integrity_enabled, integrity_status_login
from scripts.lib.config_strict import ConfigRejected, strict_settings
from scripts.lib.integrity_status import verify_integrity_status
from scripts.lib.receipt_gate import require_merge_receipt
from scripts.lib.wiki_debt import has_wiki_ingest_for_merged_prs
from scripts.post_evals import smoke_verify

Context = dict[str, Any]


def review_stage(number: str, sha: str, context: Context) -> None:
    """The current head carries a trusted, SHA-bound review artifact ($coderails-codex:post-review)."""
    review, reason = git.gate_review_summary_for_pr(number, sha)
    if review == 2:
        raise git.WorkflowError(git.trust_failure_message(reason))
    if review:
        raise git.WorkflowError(
            f"No coderails review artifact for current head {sha} — run $coderails-codex:post-review"
        )


def eval_stage(number: str, sha: str, context: Context) -> None:
    """The current head carries a trusted GO eval artifact ($coderails-codex:post-evals)."""
    summary = git.gate_eval_summary_for_pr(number, sha)
    if summary.status == 2:
        raise git.WorkflowError(git.trust_failure_message(summary.failure_reason) + " (eval artifact gate)")
    if summary.status:
        if summary.verification_level:
            raise git.WorkflowError(
                f"Eval artifact for current head {sha} is NO-GO (verification_level {summary.verification_level}) "
                "— resolve failing P0 evals and re-run $coderails-codex:post-evals"
            )
        raise git.WorkflowError(f"No coderails eval artifact for current head {sha} — run $coderails-codex:post-evals")
    context["summary"] = summary


def smoke_stage(number: str, sha: str, context: Context) -> None:
    """Every verification_level >= 1 eval is re-executed in a detached worktree at the trusted head."""
    try:
        with tempfile.TemporaryDirectory(prefix="coderails-eval-embed-") as temporary:
            embed = Path(temporary) / "embed.json"
            embed.write_text(context["summary"].embed)
            if smoke_verify(embed, sha):
                raise git.WorkflowError(
                    f"Smoke-verify failed for current head {sha}; fix the eval or artifact and re-post"
                )
    except OSError as error:
        raise git.WorkflowError("Local temporary file allocation/write failed for the smoke-verify gate") from error


def integrity_stage(number: str, sha: str, context: Context) -> None:
    """When integrity review is enabled, require its successful status on the exact head."""
    config = config_path()
    if config:
        try:
            strict_settings(config)
        except ConfigRejected as error:
            raise git.WorkflowError(str(error)) from error
        if integrity_enabled(config):
            verify_integrity_status(sha, integrity_status_login(config))


def wiki_debt_stage(number: str, sha: str, context: Context) -> None:
    """Every earlier merged PR (from wiki_debt_epoch_pr) has a wiki ingest."""
    has_wiki_ingest_for_merged_prs(number)


VERIFY_STAGES: list[tuple[str, Callable[[str, str, Context], None]]] = [
    ("review_artifact", review_stage),
    ("eval_artifact", eval_stage),
    ("eval_smoke", smoke_stage),
    ("integrity_status", integrity_stage),
    ("wiki_debt", wiki_debt_stage),
]


def describe() -> str:
    """JSON gate list from the two registries merge.py actually runs: VERIFY_STAGES, then publication_gate.CHECKS."""

    def entry(name: str, function: Callable[..., Any]) -> dict[str, str]:
        return {"name": name, "summary": (function.__doc__ or "").strip().splitlines()[0] if function.__doc__ else ""}

    return json.dumps(
        {
            "verify_gates": [entry(name, stage) for name, stage in VERIFY_STAGES],
            "publication_gate": [entry(check.__name__, check) for check in publication_gate.CHECKS],
        },
        indent=2,
    )


def verify_gates(number: str) -> str:
    """Require trusted artifacts and actual eval execution before any merge."""
    sha = git.pr_field(number, "headRefOid")
    if not sha:
        raise git.WorkflowError("GitHub fetch failed — could not resolve PR head SHA")
    context: Context = {}
    for _, stage in VERIFY_STAGES:
        stage(number, sha, context)
    return sha


def cleanup(number: str, default: str) -> None:
    """Best-effort post-merge sync and branch cleanup without changing merge success."""
    try:
        git.sync_main_branch()
        head = git.pr_field(number, "headRefName")
        if head and head != default:
            remote = git.run("git", "push", "origin", "--delete", head)
            print(f"✓ Deleted remote branch {head}" if not remote.returncode else f"! Remote branch {head} not deleted")
            local = git.run("git", "branch", "-D", head)
            print(f"✓ Deleted local branch {head}" if not local.returncode else f"! Local branch {head} kept")
        print(git.output("git", "log", "--oneline", "-5"))
    except (OSError, git.WorkflowError) as error:
        print(f"! Post-merge cleanup incomplete: {error}", file=sys.stderr)


def main(arguments: list[str] | None = None) -> int:
    """Resolve the PR and preserve all gates before calling the remote merge."""
    original = sys.argv[1:] if arguments is None else arguments
    if original == ["--describe"]:
        print(describe())
        return 0
    try:
        arguments, unit, progress = manifest_policy.unit_flags(original)
        argument = arguments[0] if arguments else "auto"
        if merge_target.has_repo_override():
            publication_gate.trace_preflight("pr_repo_override")
            raise git.WorkflowError("pr_repo_override: unset GH_REPO before merging")
        expected_sha: str | None = None
        if len(arguments) == 3 and arguments[1] == "--expected-head":
            expected_sha = arguments[2]
        elif len(arguments) == 2 and arguments[1].startswith("--expected-head="):
            expected_sha = arguments[1].split("=", 1)[1]
        elif len(arguments) > 1:
            raise git.WorkflowError("Usage: merge.py <PR or branch> [--expected-head <40-hex SHA>]")
        if expected_sha is not None and not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
            raise git.WorkflowError("--expected-head must be a full lowercase commit SHA")
        git.require_repo()
        default = git.main()
        if argument == "auto":
            if git.branch() == default:
                raise git.WorkflowError(f"On {default} ─ specify PR# or branch")
            number = merge_target.resolve("")
        else:
            number = merge_target.resolve(argument)
        if not number:
            raise git.WorkflowError(f"No PR for {argument}")
        print(f"• PR #{number} │ {git.pr_field(number, 'title', f'PR #{number}')}")
        state = git.pr_field(number, "state", "UNKNOWN")
        if state == "OPEN":
            if git.protected() and git.pr_field(number, "reviewDecision", "NONE") != "APPROVED":
                raise git.WorkflowError("Not approved")
            sha = verify_gates(number)
            if expected_sha is not None and expected_sha != sha:
                raise git.WorkflowError("PR head changed after the expected SHA was chosen")
            publication_gate.enforce(number, sha, unit=unit, progress=progress)
            command = shlex.join(["python3", sys.argv[0], *original])
            reservation = require_merge_receipt(
                number, target=argument, verified_sha=sha, expected_sha=expected_sha, command=command
            )
            # pin the head the gates verified: GitHub refuses the merge if the PR head moved since
            try:
                git.run("gh", "pr", "merge", number, "--merge", "--match-head-commit", sha, check=True)
            except git.WorkflowError:
                if reservation and git.pr_field(number, "state") == "OPEN":
                    merge_budget.settle(reservation, False)
                raise
            if reservation:
                merge_budget.settle(reservation, True)
            print("✓ Merged")
        elif state == "MERGED":
            print("! Already merged")
        else:
            raise git.WorkflowError("PR closed (not merged)" if state == "CLOSED" else "Unknown state")
        cleanup(number, default)
        print("━━━ Done ━━━")
        return 0
    except (git.WorkflowError, OSError, ValueError) as error:
        print(f"✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
