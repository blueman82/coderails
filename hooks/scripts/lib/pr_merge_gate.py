"""Fetch and validate exact-head eval evidence and machine integrity attestation."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import merge_target, publication_gate
from scripts.lib.config import config_path, integrity_machine_user
from scripts.lib.git_common import gate_eval_summary_for_pr, pr_field, repo, run
from scripts.post_evals import smoke_verify


def integrity_reason(number: str, sha: str, cwd: str) -> str:
    """Require the newest exact-SHA success from the configured machine login."""
    machine = integrity_machine_user(config_path(cwd))
    if not machine:
        return ""
    prefix = f"Blocked: gh pr merge {number} — "
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
        statuses = json.loads(result.stdout)
        status = cast(dict[str, Any], statuses[0]) if isinstance(statuses, list) and statuses else {}
        state = status.get("state", "")
        creator = status.get("creator", {}).get("login", "")
        description = status.get("description", "")
    except (OSError, ValueError, AttributeError, TypeError):
        return (
            prefix + f"no integrity-review status found for {sha}. The integrity daemon has not attested this SHA yet."
        )
    if not state:
        return (
            prefix + f"no integrity-review status found for {sha}. The integrity daemon has not attested this SHA yet."
        )
    if state != "success":
        return (
            prefix + f"integrity-review status for {sha} is '{state}' (not success). The integrity "
            f"daemon has not attested this SHA."
        )
    if creator != machine:
        return (
            prefix + f"integrity-review status for {sha} was posted by '{creator}', not the "
            f"configured machine user '{machine}'."
        )
    if (
        not isinstance(description, str)
        or not re.search(r"(^|\s)integrity=pass(\s|$)", description)
        or not re.search(r"(^|\s)sha=" + re.escape(sha) + r"(\s|$)", description)
    ):
        return (
            prefix + f"integrity-review status for {sha} is not a valid SHA-bound pass attestation. "
            f"Do not bypass; investigate."
        )
    return ""


def merge_reason(number: str, cwd: str, unit: str = "", progress: str = "") -> str:
    """Return the fail-closed merge denial, or empty after live evidence re-execution."""
    try:
        os.chdir(cwd)
    except OSError:
        return (
            "Blocked: could not resolve working directory to verify the eval artifact for "
            "gh pr merge. Retry from a valid repo directory."
        )
    number = merge_target.resolve(number)  # no target = this branch's PR; "?", other-repo URL, unknown branch = none
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
    if violations := publication_gate.evaluate(number, sha, unit=unit, progress=progress):
        first = violations[0]
        fix = (
            "Fix the diff or the policy; set diff_manifest: off only on purpose."
            if first["code"].startswith("diff_manifest")
            else "Run the required reviews, then re-post: post_review.py post <PR> --summary F --pass NAME=F."
        )
        detail = first["detail"] or "no detail"
        return f"{first['code']}: {prefix}the publication gate refused this head ({detail}). {fix}"
    return integrity_reason(number, sha, cwd)
