"""The one publication gate every path to a merge calls: merge.py, headless runs and the direct-merge hooks.

`CHECKS` is an ordered list of check functions `check(number, sha, unit, progress) -> [{code, detail}]`. U1 registers
the diff manifest; later units append their own (review passes, eval level) and need no new call site. `evaluate`
returns every violation, `enforce` raises WorkflowError whose text starts with the first reason code. Each refusal
writes a `publication/refused/<code>` trace row; rows never decide anything.
"""

from __future__ import annotations

from collections.abc import Callable

from . import git_common as git
from . import manifest_policy

Violation = dict[str, str]
Check = Callable[[str, str, str, str], list[Violation]]


def manifest_check(number: str, sha: str, unit: str, progress: str) -> list[Violation]:
    """Diff-manifest policy for the PR head (mode, default policy and unit manifest are handled there)."""
    return manifest_policy.violations(number, unit, progress, head=sha)


CHECKS: list[Check] = [manifest_check]


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
