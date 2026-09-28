"""Git workflow primitives and authenticated, SHA-bound PR artifact readers."""

from __future__ import annotations

import base64
import binascii
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from . import eval_artifact, review_artifact
from .eval_validation import extract_json_block


class WorkflowError(RuntimeError):
    """Report a workflow failure without continuing consequential operations."""


class TrustFetchError(WorkflowError):
    """Identify the failed authenticated comment lookup stage."""


def run(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a literal argv with captured output and optional failure propagation."""
    result = subprocess.run(arguments, capture_output=True, text=True, check=False)
    if check and result.returncode:
        raise WorkflowError(
            result.stderr.strip() or result.stdout.strip() or f"{arguments[0]} failed ({result.returncode})"
        )
    return result


def output(*arguments: str, check: bool = False) -> str:
    """Return trimmed stdout from a literal external command."""
    return run(*arguments, check=check).stdout.strip()


def branch() -> str:
    """Return the checked-out branch name."""
    return output("git", "branch", "--show-current")


def dirty() -> bool:
    """Report tracked or untracked working tree changes."""
    return bool(output("git", "status", "-s"))


def clean() -> bool:
    """Report whether the working tree has no reported changes."""
    return not dirty()


def main() -> str:
    """Resolve the remote default branch, defaulting to main."""
    return output("git", "symbolic-ref", "refs/remotes/origin/HEAD").rsplit("/", 1)[-1] or "main"


def ahead() -> int:
    """Count commits ahead of the remote default branch."""
    result = run("git", "rev-list", "--count", f"origin/{main()}..HEAD")
    return int(result.stdout.strip() or "0") if result.returncode == 0 else 0


def ahead_list() -> str:
    """List local commits since the remote default branch."""
    return output("git", "log", f"origin/{main()}..HEAD", "--oneline")


def repo_from_url(url: str) -> str:
    """Extract github.com owner/repository while preserving dotted names."""
    match = re.search(r"github\.com[:/]([^/]+)/(.+)$", url)
    if not match:
        return ""
    name = match[2].removesuffix("/").removesuffix(".git")
    return f"{match[1]}/{name}"


def repo() -> str:
    """Resolve the current origin GitHub repository."""
    return repo_from_url(output("git", "remote", "get-url", "origin"))


def protected() -> bool:
    """Report whether branch protection requires PR reviews."""
    return "required_pull_request_reviews" in output("gh", "api", f"repos/{repo()}/branches/{main()}/protection")


def pr_num(head: str = "") -> str:
    """Return the first PR associated with a branch."""
    return output("gh", "pr", "list", "--head", head or branch(), "--json", "number", "-q", ".[0].number")


def pr_field(number: str, field: str, fallback: str = "") -> str:
    """Fetch one PR field, retaining a caller-selected failure sentinel."""
    result = run("gh", "pr", "view", number, "--json", field, "-q", f".{field}")
    return result.stdout.strip() if result.returncode == 0 else fallback


def trusted_comment_bodies(number: str) -> list[str]:
    """Fetch every comment authored by the authenticated identity with write access."""
    trusted = os.environ.get("_PR_TRUSTED_LOGIN", "")
    if not trusted:
        identity = run("gh", "api", "user", "-q", ".login")
        if identity.returncode:
            raise TrustFetchError("identity")
        trusted = identity.stdout.strip()
    if not re.fullmatch(r"[A-Za-z0-9-]+", trusted):
        raise TrustFetchError("identity")
    permission = os.environ.get("_PR_TRUSTED_PERMISSION", "")
    if not permission:
        permissions = run("gh", "repo", "view", repo(), "--json", "viewerPermission", "-q", ".viewerPermission")
        if permissions.returncode or not permissions.stdout.strip():
            raise TrustFetchError("permission")
        permission = permissions.stdout.strip()
    if permission not in ("ADMIN", "MAINTAIN", "WRITE"):
        return []
    comments = run(
        "gh",
        "api",
        f"repos/{repo()}/issues/{number}/comments",
        "--paginate",
        "--jq",
        f'.[] | select(.user.login == "{trusted}") | (.body | @base64)',
    )
    if comments.returncode:
        raise TrustFetchError("comments")
    bodies: list[str] = []
    for encoded in comments.stdout.splitlines():
        if not encoded:
            continue
        try:
            bodies.append(base64.b64decode(encoded, validate=True).decode())
        except (binascii.Error, UnicodeDecodeError):
            print("! Skipping a trusted comment body: base64 decode failed", file=sys.stderr)
    return bodies


@dataclass(frozen=True)
class EvalSummary:
    """Carry the newest trusted verdict and embedded executable evidence."""

    status: int
    verification_level: str = ""
    embed: str = ""
    failure_reason: str = ""


def gate_eval_summary_for_pr(number: str, sha: str) -> EvalSummary:
    """Return status 0 for newest GO, 1 for absent/NO-GO, or 2 for fetch failure."""
    try:
        bodies = trusted_comment_bodies(number)
    except (TrustFetchError, OSError) as error:
        return EvalSummary(2, failure_reason=str(error))
    summary = EvalSummary(1)
    for body in bodies:
        for line in body.splitlines():
            if eval_artifact.matches_marker(line, number, sha):
                summary = EvalSummary(
                    0 if eval_artifact.parse_result(line) == "GO" else 1,
                    eval_artifact.parse_verification_level(line),
                    extract_json_block(body),
                )
    return summary


def gate_review_summary_for_pr(number: str, sha: str) -> tuple[int, str]:
    """Return review status with a distinct failing trust-lookup stage."""
    try:
        bodies = trusted_comment_bodies(number)
    except (TrustFetchError, OSError) as error:
        return 2, str(error)
    matched = any(review_artifact.matches_marker(line, number, sha) for body in bodies for line in body.splitlines())
    return (0 if matched else 1), ""


def has_coderails_review_for_head(number: str, sha: str) -> int:
    """Return 0 for exact trusted review, 1 if absent, or 2 on fetch failure."""
    status, reason = gate_review_summary_for_pr(number, sha)
    if status == 2:
        print(f"TRUST_FETCH_FAIL_REASON={reason}", file=sys.stderr)
    return status


def trust_failure_message(reason: str) -> str:
    """Explain which authenticated evidence fetch failed without obscuring its cause."""
    if reason == "tempfile":
        return "Local temporary file allocation failed before any GitHub fetch. Check temporary-directory permissions."
    stage = {
        "identity": "could not resolve the authenticated identity (gh api user)",
        "permission": "could not resolve repo permission for the authenticated identity",
        "comments": "could not fetch PR comments",
    }.get(reason, "could not fetch trusted PR evidence")
    return f"GitHub fetch failed — {stage}. Retry, or check gh auth/network."


def sync_main_branch() -> None:
    """Best-effort sync the primary checkout after a successful remote merge."""
    try:
        default = main()
        linked = output("git", "rev-parse", "--git-dir") != output("git", "rev-parse", "--git-common-dir")
        prefix = ["git"]
        if linked:
            entries = output("git", "worktree", "list", "--porcelain").splitlines()
            primary = next((line.removeprefix("worktree ") for line in entries if line.startswith("worktree ")), "")
            if not primary:
                print(f"! Could not sync {default} in primary tree — sync it manually")
                return
            prefix += ["-C", primary]
        if (
            run(*prefix, "checkout", default).returncode
            or run(*prefix, "pull", "origin", default, "--quiet").returncode
        ):
            print(f"! Could not sync {default} — sync it manually")
        else:
            print(f"✓ Synced to {default}")
    except OSError as error:
        print(f"! Could not sync default branch — sync it manually ({error})")


def require_feature() -> None:
    """Refuse changes that would use a protected default branch."""
    if branch() in ("main", "master"):
        raise WorkflowError("Switch to a feature branch first")


def require_repo() -> None:
    """Require a GitHub origin before remote workflow operations."""
    if not repo():
        raise WorkflowError("Not a GitHub repository")


def require_clean() -> None:
    """Refuse a workflow requiring a clean working directory."""
    if dirty():
        raise WorkflowError("Uncommitted changes - commit or stash first")
