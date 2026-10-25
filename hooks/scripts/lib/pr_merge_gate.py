"""Fetch and validate exact-head eval evidence and GitHub Actions attestation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.artifact_io import array_value
from scripts.lib.config import config_path, integrity_enabled, integrity_status_login
from scripts.lib.config_strict import ConfigRejected, strict_settings
from scripts.lib.git_common import branch, gate_eval_summary_for_pr, pr_field, pr_num, repo, run
from scripts.lib.integrity_attestation import parse_attestation
from scripts.post_evals import smoke_verify


def integrity_reason(number: str, sha: str, cwd: str, session: str = "") -> str:
    """Require one parsed exact-SHA GitHub Actions status when configured."""
    path = config_path(cwd)
    if not path:
        return ""
    prefix = f"Blocked: gh pr merge {number} — "
    try:
        strict_settings(path)
    except ConfigRejected as error:
        return prefix + str(error)
    if not integrity_enabled(path):
        return ""
    expected_login = integrity_status_login(path)
    try:
        result = run(
            "gh",
            "api",
            f"repos/{repo()}/commits/{sha}/statuses",
            "--paginate",
            "--jq",
            '[.[] | select(.context == "integrity-review")]',
        )
        if result.returncode:
            return (
                prefix + f"GitHub fetch failed, could not fetch integrity-review status for {sha}. Retry, "
                f"or check gh auth/network."
            )
        decoder = json.JSONDecoder()
        remaining = result.stdout.lstrip()
        statuses: list[object] = []
        while remaining:
            page, end = decoder.raw_decode(remaining)
            if not isinstance(page, list):
                raise ValueError("malformed status page")
            statuses.extend(array_value(cast(object, page)))
            remaining = remaining[end:].lstrip()
        status = cast(dict[str, Any], statuses[0]) if statuses else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return prefix + f"no integrity-review status found for {sha}. GitHub Actions has not attested this SHA yet."
    verdict = parse_attestation(status, sha, expected_login)
    if not verdict.ok:
        append_row("pr_merge_gate", "denied", verdict.reason_code, session, inputs={"sha": sha})
        return prefix + f"{verdict.reason_code}: {verdict.detail}. GitHub Actions has not attested this SHA."
    return ""


def merge_reason(number: str, cwd: str, session: str = "") -> str:
    """Return the fail-closed merge denial, or empty after live evidence re-execution."""
    try:
        os.chdir(cwd)
    except OSError:
        return (
            "Blocked: could not resolve working directory to verify the eval artifact for "
            "gh pr merge. Retry from a valid repo directory."
        )
    number = number or pr_num(branch())
    if not number:
        return (
            "Blocked: gh pr merge — could not resolve a PR number to verify the eval "
            "artifact. Retry, or check gh auth/network."
        )
    prefix = f"Blocked: gh pr merge {number} — "
    sha = pr_field(number, "headRefOid")
    if not sha:
        return prefix + "GitHub fetch failed, could not resolve PR head SHA. Retry, or check gh auth/network."
    summary = gate_eval_summary_for_pr(number, sha)
    if summary.status == 2:
        descriptions = {
            "identity": "resolve the authenticated identity (gh api user)",
            "permission": "resolve repo permission",
            "tempfile": "allocate local temporary file",
        }
        stage = descriptions.get(summary.failure_reason, "fetch PR comments")
        return (
            prefix
            + f"GitHub fetch failed, could not {stage} for the eval artifact gate. Retry, or check gh auth/network."
        )
    if summary.status != 0:
        if summary.verification_level:
            return (
                prefix + f"eval artifact for current head {sha} is NO-GO (verification_level "
                f"{summary.verification_level}). Resolve failing P0 evals and re-run "
                f"/coderails:post-evals."
            )
        return (
            prefix + f"no coderails eval artifact for current head {sha}. Run /coderails:task-evals "
            f"then /coderails:post-evals after /pr-review-toolkit:review-pr."
        )
    if not summary.embed:
        return (
            prefix
            + f"no coderails eval artifact embed found for current head {sha}. Investigate the mismatch before merging."
        )
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evals.json"
            path.write_text(summary.embed)
            if smoke_verify(path, sha):
                return (
                    prefix + f"smoke-verify failed for current head {sha}. One or more scripted evals could "
                    f"not be confirmed by gate-time re-execution against the trusted commit. Do not "
                    f"bypass; fix the eval or the artifact and re-post."
                )
    except (OSError, ValueError):
        return (
            prefix + "local temporary file allocation failed for the smoke-verify gate. Check /tmp "
            "disk space or permissions, then retry."
        )
    return integrity_reason(number, sha, cwd, session)
