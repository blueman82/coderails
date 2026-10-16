"""One ordered publication gate for merge commands, headless runs and direct hooks; traces never decide."""

from __future__ import annotations

import json
from collections.abc import Callable

from . import eval_artifact, eval_level, manifest_policy, review_passes
from . import git_common as git
from .artifact_io import object_value
from .config import config_path, load_config
from .eval_integrity import IntegrityError, suite_hash

Violation = dict[str, str]
Check = Callable[[str, str, str, str], list[Violation]]


def manifest_check(number: str, sha: str, unit: str, progress: str) -> list[Violation]:
    """Diff-manifest policy for the PR head (mode, default policy and unit manifest are handled there)."""
    return manifest_policy.violations(number, unit, progress, head=sha)


def review_passes_check(number: str, sha: str, unit: str, progress: str) -> list[Violation]:
    """Require live-diff reviews from the newest exact-head artifact; only explicit off skips."""
    values, _ = load_config(config_path() or "")
    if str(values.get("review_passes") or "enforce") == "off":
        manifest_policy.trace(f"{git.repo()}@pr-{number}", "skipped", "review_passes_off", command="review-passes")
        return []
    found = git.review_passes_for_pr(number, sha)
    if found.status:
        return [{"code": "review_artifact_missing", "detail": found.failure_reason or "no artifact for this head"}]
    if found.passes is None:
        return [{"code": "review_passes_malformed", "detail": ""}]
    try:
        policy = review_passes.load_policy()
        changes = manifest_policy.diff_changes(sha, f"pull/{number}/head")
    except ValueError:
        return [{"code": "review_policy_unreadable", "detail": ""}]
    if changes is None:
        return [{"code": "review_policy_unreadable", "detail": "diff unavailable"}]
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


def eval_level_check(number: str, sha: str, unit: str, progress: str) -> list[Violation]:
    """Require a current-head GO suite with matching level, computed lateness and hash.

    The live diff/unit lower bounds set the floor; level >= 1 must be frozen. Only eval_level: off skips.
    """
    values, _ = load_config(config_path() or "")
    if str(values.get("eval_level") or "enforce") == "off":
        manifest_policy.trace(f"{git.repo()}@pr-{number}", "skipped", "eval_level_off", command="eval-level")
        return []
    found = git.gate_eval_summary_for_pr(number, sha)
    if found.status == 2:
        return [{"code": "eval_artifact_unreadable", "detail": found.failure_reason}]
    if found.status or not found.embed:
        return [{"code": "eval_artifact_missing", "detail": "no GO eval artifact for this head"}]
    try:
        data = object_value(json.loads(found.embed))
    except ValueError:  # JSONDecodeError and the non-object case
        return [{"code": "eval_embed_malformed", "detail": ""}]
    if str(data.get("verification_level", "")) != found.verification_level:
        return [{"code": "eval_embed_malformed", "detail": "marker and embedded verification_level differ"}]
    changes = eval_level.pr_changes(number, sha)
    if changes is None:
        return [{"code": "eval_level_diff_unavailable", "detail": ""}]
    _, minimum = eval_level.derive(changes, eval_level.progress_units(progress), data, eval_level.load_policy())
    late = eval_level.suite_late(data, eval_level.branch_base(sha))
    codes: list[str] = []
    if data.get("head_sha") != sha:
        codes.append("eval_head_mismatch")
    if not eval_artifact.compute_go(data):
        codes.append("eval_result_mismatch")
    if int(found.verification_level) < minimum:
        codes.append("level_below_derived")
    stamped = eval_artifact.parse_facts(found.facts)
    if stamped is None:
        codes += ["eval_facts_missing"] if minimum or late else []
    elif stamped[1] != late:
        codes.append("late_freeze_unstamped")
    try:
        eval_level.check_suite(data, found.verification_level, stamped=True)
    except IntegrityError as error:
        codes.append(error.code)
    if stamped is not None and stamped[2] != suite_hash(data)[:16]:
        codes.append("suite_hash_marker_mismatch")
    label = f"{git.repo()}@pr-{number}"
    for code in codes or ["eval_level_ok"]:
        manifest_policy.trace(label, "refused" if codes else "ok", code, command="eval-level")
    detail = f"derived_min_level={minimum} marker={found.verification_level}"
    return [{"code": code, "detail": detail} for code in codes]


CHECKS: list[Check] = [manifest_check, review_passes_check, eval_level_check]


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
    if code.startswith(("eval_", "level_", "late_freeze", "suite_", "chain_", "integrity_", "not_frozen")):
        return "Re-run and re-post the evals: post_evals.py post <PR> <evals.json> (record an oracle edit with amend)."
    return "Resolve the reported publication-check refusal, then retry."


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
