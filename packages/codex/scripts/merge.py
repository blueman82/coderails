#!/usr/bin/env python3
"""Verify exact-head review, eval, integrity and wiki evidence before merging."""

from __future__ import annotations

import re
import shlex
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import git_common as git
from scripts.lib import manifest_policy, merge_budget
from scripts.lib.config import config_path, integrity_enabled, integrity_status_login
from scripts.lib.config_strict import ConfigRejected, strict_settings
from scripts.lib.integrity_status import verify_integrity_status
from scripts.lib.receipt_gate import require_merge_receipt
from scripts.lib.wiki_debt import has_wiki_ingest_for_merged_prs
from scripts.post_evals import smoke_verify


def verify_gates(number: str) -> str:
    """Require trusted artifacts and actual eval execution before any merge; return the verified head SHA."""
    sha = git.pr_field(number, "headRefOid")
    if not sha:
        raise git.WorkflowError("GitHub fetch failed — could not resolve PR head SHA")
    review, reason = git.gate_review_summary_for_pr(number, sha)
    if review == 2:
        raise git.WorkflowError(git.trust_failure_message(reason))
    if review:
        raise git.WorkflowError(
            f"No coderails review artifact for current head {sha} — run $coderails-codex:post-review"
        )
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
    try:
        with tempfile.TemporaryDirectory(prefix="coderails-eval-embed-") as temporary:
            embed = Path(temporary) / "embed.json"
            embed.write_text(summary.embed)
            if smoke_verify(embed, sha):
                raise git.WorkflowError(
                    f"Smoke-verify failed for current head {sha}; fix the eval or artifact and re-post"
                )
    except OSError as error:
        raise git.WorkflowError("Local temporary file allocation/write failed for the smoke-verify gate") from error
    config = config_path()
    if config:
        try:
            strict_settings(config)
        except ConfigRejected as error:
            raise git.WorkflowError(str(error)) from error
        if integrity_enabled(config):
            verify_integrity_status(sha, integrity_status_login(config))
    has_wiki_ingest_for_merged_prs(number)
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
    arguments = sys.argv[1:] if arguments is None else arguments
    argument = arguments[0] if arguments else "auto"
    try:
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
            number = git.pr_num()
        else:
            number = argument if argument[:1].isdigit() else git.pr_num(argument)
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
            manifest_policy.gate(number)
            command = shlex.join(["python3", sys.argv[0], *arguments])
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
