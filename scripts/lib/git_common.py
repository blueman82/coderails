"""Git workflow primitives and authenticated, SHA-bound PR artifact readers."""

from __future__ import annotations

import base64
import binascii
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from . import eval_artifact, review_artifact, review_passes
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
    facts: str = ""  # line 2 of the body when it is a coderails-eval-facts line, else empty


def gate_eval_summary_for_pr(number: str, sha: str) -> EvalSummary:
    """Return status 0 for newest GO, 1 for absent/NO-GO, or 2 for fetch failure."""
    try:
        bodies = trusted_comment_bodies(number)
    except (TrustFetchError, OSError) as error:
        return EvalSummary(2, failure_reason=str(error))
    summary = EvalSummary(1)
    for body in bodies:
        lines = body.splitlines()
        for index, line in enumerate(lines):
            if eval_artifact.matches_marker(line, number, sha):
                following = lines[index + 1] if index + 1 < len(lines) else ""
                summary = EvalSummary(
                    0 if eval_artifact.parse_result(line) == "GO" else 1,
                    eval_artifact.parse_verification_level(line),
                    extract_json_block(body),
                    facts=following if eval_artifact.parse_facts(following) else "",
                )
    return summary


def gate_review_summary_for_pr(number: str, sha: str) -> tuple[int, str]:
    """Return (status, reason): 0 present, 1 absent, 2 fetch failure (stage), 3 compat refusal (reason code)."""
    try:
        bodies = trusted_comment_bodies(number)
    except (TrustFetchError, OSError) as error:
        return 2, str(error)
    matching = [
        body for body in bodies if any(review_artifact.matches_marker(line, number, sha) for line in body.splitlines())
    ]
    if not matching:
        return 1, ""
    problem = review_artifact.compat_problem(matching, number, sha)
    return (3, problem) if problem else (0, "")


@dataclass(frozen=True)
class ReviewPasses:
    """Newest trusted review artifact for a head: status 0 found, 1 absent, 2 fetch failed; passes None: malformed."""

    status: int
    passes: tuple[dict[str, Any], ...] | None = ()
    failure_reason: str = ""


def review_passes_for_pr(number: str, sha: str) -> ReviewPasses:
    """Accept a server-compatible summary only when it exactly follows its bound pass record."""
    try:
        bodies = trusted_comment_bodies(number)
    except (TrustFetchError, OSError) as error:
        return ReviewPasses(2, None, str(error))
    positions = [
        index
        for index, body in enumerate(bodies)
        if body.splitlines() and review_artifact.matches_marker(body.splitlines()[0], number, sha)
    ]
    if not positions:
        return ReviewPasses(1)
    last = positions[-1]
    companion = bodies[last]
    marker = review_artifact.marker(number, sha)
    if companion.splitlines()[1:2] and companion.splitlines()[1].startswith("<!-- coderails-review-passes"):
        return ReviewPasses(0, None)
    earlier_pass = any(body.startswith(marker + "\n<!-- coderails-review-passes") for body in bodies[:last])
    if not earlier_pass:
        lines = companion.splitlines()[1:]
        if lines and lines[0].startswith("<!-- coderails-compat-findings"):
            lines = lines[1:]
        summary = "\n".join(lines)
        try:
            review_passes.validate_summary_text(summary)
        except ValueError:
            return ReviewPasses(0, None)
        verdict = review_passes.verdict_from_summary(summary)
        entry = {
            "name": "review-pr",
            "verdict": verdict,
            "blocking": verdict == "fail",
            "summary_sha256": review_passes.summary_sha256(summary),
        }
        return ReviewPasses(0, (entry,))
    previous = bodies[last - 1]
    if not previous.startswith(marker + "\n" + review_passes.PREFIX):
        return ReviewPasses(0, None)
    parsed = review_passes.parse(previous, number, sha)
    if parsed is None or not parsed:
        return ReviewPasses(0, None)
    _, _, remainder = previous.partition("\n")
    _, _, summary = remainder.partition("\n")
    general, separator, _ = summary.partition("\n<!-- coderails-review-pass ")
    if separator:
        summary = general
    if companion != marker + "\n" + summary:
        return ReviewPasses(0, None)
    return ReviewPasses(0, tuple(parsed))


def has_coderails_review_for_head(number: str, sha: str) -> int:
    """Return 0 for exact trusted review, 1 if absent, or 2 on fetch failure (a compat refusal is still a review)."""
    status, reason = gate_review_summary_for_pr(number, sha)
    if status == 2:
        print(f"TRUST_FETCH_FAIL_REASON={reason}", file=sys.stderr)
    return 0 if status == 3 else status


def compat_failure_message(reason: str) -> str:
    """Explain a status-3 review gate result; the closed reason code is part of the text."""
    if reason == "compat_findings_missing":
        return (
            "The review artifact needs a compat-findings line for the current PR head "
            "[reason_code=compat_findings_missing]"
        )
    if reason == "compat_findings_malformed":
        return "A compat-findings line on the review artifact is malformed [reason_code=compat_findings_malformed]"
    return (
        "The review reported compat findings on a clean-break change; remove the compatibility code or set a "
        f"preserve-compat disposition with a named blocker and removal ticket [reason_code={reason}]"
    )


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
