"""The one publication gate every path to a merge calls: merge.py, headless runs and the direct-merge hooks.

`CHECKS` is an ordered list of check functions `check(number, sha, unit, progress) -> [{code, detail}]`. U1 registers
the diff manifest and U2 the review passes; later units append their own (eval level), no new call site. `evaluate`
returns every violation, `enforce` raises WorkflowError whose text starts with the first reason code. Each refusal
writes a `publication/refused/<code>` trace row; rows never decide anything.
"""

from __future__ import annotations

from collections.abc import Callable

from . import git_common as git
from . import manifest_policy, review_passes
from .config import config_path, load_config

Violation = dict[str, str]
Check = Callable[[str, str, str, str], list[Violation]]


def manifest_check(number: str, sha: str, unit: str, progress: str) -> list[Violation]:
    """Diff-manifest policy for the PR head (mode, default policy and unit manifest are handled there)."""
    return manifest_policy.violations(number, unit, progress, head=sha)


def review_passes_check(number: str, sha: str, unit: str, progress: str) -> list[Violation]:
    """Required reviewers for the diff (policy/review_policy.json) against the passes in the SHA-bound artifact.

    `review-pr` is satisfied by the v1 marker itself; a v1 artifact with no passes line has passes=[]. A pass counts
    only with verdict `pass`; the artifact's `blocking` flag never waives a required pass. Fails closed. Config
    `review_passes: off` skips the check; absent or any other value enforces.
    """

    def refused(code: str, detail: str = "") -> list[Violation]:
        manifest_policy.trace(f"{git.repo()}@pr-{number}", "refused", code, command="review-passes")
        return [{"code": code, "detail": detail}]

    values, _ = load_config(config_path() or "")
    if str(values.get("review_passes") or "enforce") == "off":
        manifest_policy.trace(f"{git.repo()}@pr-{number}", "skipped", "review_passes_off", command="review-passes")
        return []
    found = git.review_passes_for_pr(number, sha)
    if found.status:
        return refused("review_artifact_missing", found.failure_reason or "no artifact for this head")
    if found.passes is None:
        return refused("review_passes_malformed")
    try:
        policy = review_passes.load_policy()
        base = git.pr_field(number, "baseRefOid")
        changes = manifest_policy.diff_changes(sha, f"pull/{number}/head", base) if base else None
    except ValueError:
        return refused("review_policy_unreadable")
    if changes is None:
        return refused("review_policy_unreadable", "diff unavailable")
    verdicts = {p["name"]: p["verdict"] for p in found.passes}
    needed = review_passes.required(changes, policy)
    # a failed pass that marks itself blocking refuses even when the policy did not ask for it
    extra = [p["name"] for p in found.passes if p["verdict"] == "fail" and p["blocking"] and p["name"] not in needed]
    names = needed + extra
    problems: list[Violation] = []
    for name in names:
        if name in needed and name != "review-pr" and name not in verdicts:
            problems.append({"code": f"required_review_missing:{name}", "detail": ""})
        elif verdicts.get(name) == "fail":
            problems.append({"code": f"required_review_failed:{name}", "detail": ""})
    label = f"{git.repo()}@pr-{number}"
    for code in [v["code"] for v in problems] or ["review_passes_ok"]:
        manifest_policy.trace(label, "refused" if problems else "ok", code, command="review-passes")
    return problems


CHECKS: list[Check] = [manifest_check, review_passes_check]


def remediation(code: str) -> str:
    """Prescribe a repair for the refused check; an unreadable policy or runtime error needs no new artifact."""
    if code == "review_policy_unreadable":
        return "Restore a readable policy/review_policy.json and check that the current-head diff is available."
    if code.endswith("_error"):
        return "Investigate the reported publication-check error, repair its cause, then retry."
    if code.startswith("diff_manifest"):
        return "Fix the diff or the policy; set diff_manifest: off only on purpose."
    if code.startswith("required_review_") or code in ("review_artifact_missing", "review_passes_malformed"):
        return "Run the required reviews, then re-post: post_review.py post <PR> --summary F --pass NAME=F."
    return "Resolve the reported publication-check refusal, then retry."


def trace_preflight(code: str) -> None:
    """Count a repository or base retarget refusal before PR evidence can be trusted."""
    manifest_policy.trace("merge-preflight", "refused", code, command="publication")


def evaluate(number: str, sha: str, unit: str = "", progress: str = "") -> list[Violation]:
    """Run every registered check; a check that raises is a refusal, never a pass."""
    found: list[Violation] = []
    for check in CHECKS:
        try:
            found += check(number, sha, unit, progress)
        except Exception as error:  # noqa: BLE001 - fail closed: an erroring check must not publish
            code = "diff_manifest:manifest_internal_error" if check is manifest_check else f"{check.__name__}_error"
            found.append({"code": code, "detail": type(error).__name__})
    try:
        label = f"{git.repo()}@pr-{number}"
    except Exception:  # noqa: BLE001 - trace metadata must never change the verdict
        label = f"pr-{number}"
    for violation in found:
        manifest_policy.trace(label, "refused", violation["code"], command="publication")
    return found


def enforce(number: str, sha: str, unit: str = "", progress: str = "") -> None:
    """Raise WorkflowError("<code>: <detail>") for the first violation."""
    found = evaluate(number, sha, unit, progress)
    if not found:
        return
    first = found[0]
    raise git.WorkflowError(f"{first['code']}: {first['detail']}" if first["detail"] else first["code"])
