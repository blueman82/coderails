"""Derived minimum verification level, late-freeze computation and suite integrity for a PR-scope eval suite.

The level is a floor computed from the diff (policy/surface_policy.json), never a self-assignment: level 0 only for
one work unit with no outward surface, level 1 for any outward surface or 2 units, level 2 for irreversible surfaces
or >= `level_2_work_units` units (skills/task-evals/SKILL.md "Verification level rules"). Declared `facts` in the
suite count only as a lower bound. Limit: the work-unit count comes from progress.json when `--progress` resolves,
else from the declared lower bound; a diff alone cannot show how many units produced it.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast

from .artifact_io import JsonObject
from .eval_integrity import INTEGRITY_STRIPPED, IntegrityError, verify_suite

POLICY = Path(__file__).resolve().parents[2] / "policy" / "surface_policy.json"
NOT_FROZEN = "not_frozen"
SURFACES = ("outward", "irreversible")  # ascending severity
Changes = list[tuple[str, list[str]]]


def load_policy(path: str | Path = POLICY) -> dict[str, Any]:
    """The surface policy; a missing, torn or ill-shaped file raises ValueError("surface_policy_unreadable")."""
    try:
        data = cast(dict[str, Any], json.loads(Path(path).read_text()))
        ok = all(_strings(data[k]) for k in ("none", "irreversible", "outward"))
        ok = ok and isinstance(data["level_2_work_units"], int) and not isinstance(data["level_2_work_units"], bool)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("surface_policy_unreadable") from error
    if not ok:
        raise ValueError("surface_policy_unreadable")
    return data


def _strings(value: object) -> bool:
    """Whether the value is a list of strings."""
    return isinstance(value, list) and all(isinstance(x, str) for x in cast(list[object], value))


def classify(path: str, policy: dict[str, Any]) -> str:
    """Classify a path: irreversible first, then none (anchored docs and test dirs), else outward (fail closed)."""
    from .manifest_policy import matches  # lazy: manifest_policy imports git_common, which imports eval_validation

    for name in ("irreversible", "none"):
        if matches(path, policy[name]):
            return name
    return "outward"


def facts_from_changes(changes: Changes, progress_units: int = 0, policy: dict[str, Any] | None = None) -> JsonObject:
    """{work_units, surfaces}: surfaces of every touched path (rename: both sides), units from progress.json (>= 1)."""
    policy = policy or load_policy()
    found = {classify(p, policy) for _, paths in changes for p in paths}
    return {"work_units": max(1, progress_units), "surfaces": [s for s in SURFACES if s in found]}


def derive_min_level(facts: JsonObject, policy: dict[str, Any]) -> int:
    """0, 1 or 2 from the facts and the policy."""
    surfaces, units = cast(list[str], facts["surfaces"]), cast(int, facts["work_units"])
    if "irreversible" in surfaces or units >= policy["level_2_work_units"]:
        return 2
    return 1 if "outward" in surfaces or units >= 2 else 0


def derive(changes: Changes, progress_units: int, data: JsonObject, policy: dict[str, Any]) -> tuple[JsonObject, int]:
    """(facts, level): computed facts raised, never lowered, by declared or posted facts."""
    facts = facts_from_changes(changes, progress_units, policy)
    for key in ("facts", "gate_facts"):
        declared = data.get(key)
        if isinstance(declared, dict):
            units = cast(JsonObject, declared).get("work_units")
            if isinstance(units, int) and not isinstance(units, bool):
                facts["work_units"] = max(cast(int, facts["work_units"]), units)
            extra = cast(JsonObject, declared).get("surfaces")
            named = {str(s) for s in cast(list[object], extra)} if isinstance(extra, list) else set[str]()
            facts["surfaces"] = [s for s in SURFACES if s in named | set(cast(list[str], facts["surfaces"]))]
    return facts, derive_min_level(facts, policy)


def _git(*args: str, directory: str = ".") -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", directory, *args], capture_output=True, text=True, check=False)


def late_freeze(frozen_sha: str, base: str, directory: str = ".") -> bool:
    """True unless frozen_sha is a full 40-hex commit that is an ancestor of the branch base.

    Empty, abbreviated or rev-expression values (origin/main, HEAD~50) and unresolvable shas cannot be shown to precede
    the base, so they count as late. Only a missing base (no origin ref to compare with) returns False.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", frozen_sha):
        return True
    if not base:
        return False
    return _git("merge-base", "--is-ancestor", frozen_sha, base, directory=directory).returncode != 0


def suite_late(data: JsonObject, base: str, directory: str = ".") -> bool:
    """late_freeze for a suite: a level-0 suite may omit frozen_sha, every other missing or unverifiable one is late."""
    frozen = str(data.get("frozen_sha") or "")
    if not frozen and str(data.get("verification_level")) == "0":
        return False
    return late_freeze(frozen, base, directory)


def branch_base(head: str, directory: str = ".", pr: str = "") -> str:
    """merge-base of the PR target (or local default branch) and head, or empty text."""
    from . import git_common as git

    target = git.pr_field(pr, "baseRefOid") if pr else f"origin/{git.main()}"
    if pr and not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", target):
        raise ValueError("eval_level_diff_unavailable: PR base SHA unavailable")
    result = _git("merge-base", target, head, directory=directory)
    if pr and result.returncode:
        raise ValueError("eval_level_diff_unavailable: PR base merge-base unavailable")
    return result.stdout.strip() if result.returncode == 0 else ""


def pr_changes(pr: str, head: str) -> Changes | None:
    """Diff the PR base to head, or local default to head without a PR; None if unavailable."""
    from . import git_common as git
    from . import manifest_policy

    base = git.pr_field(pr, "baseRefOid") if pr else ""
    if pr and (not base or not head):
        return None
    return manifest_policy.diff_changes(head or "HEAD", f"pull/{pr}/head" if pr else "", base)


def progress_units(progress: str) -> int:
    """Number of work_units in a resolvable progress.json, else 0."""
    from . import manifest_policy

    state = manifest_policy.load_json(progress) if progress else None
    units = (state or {}).get("work_units")
    return len(cast(dict[str, Any], units)) if isinstance(units, dict) else 0


def check_suite(data: JsonObject, level: str, stamped: bool = False) -> None:
    """Raise IntegrityError unless the suite equals its freeze (or amendment chain) and, at level >= 1, is frozen."""
    verify_suite(data, stamped=stamped)
    if level != "0" and not data.get("frozen_hash"):
        code = INTEGRITY_STRIPPED if data.get("signature") else NOT_FROZEN
        raise IntegrityError(code, "a level >= 1 suite must carry the frozen_hash smoke-run stamps")
    if level != "0" and not re.fullmatch(r"[0-9a-f]{40}", str(data.get("frozen_sha") or "")):
        raise IntegrityError(NOT_FROZEN, "a level >= 1 suite must carry a full 40-hex frozen_sha")
