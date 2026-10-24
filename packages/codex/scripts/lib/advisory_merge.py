"""Receipt-independent reservations for advisory merges with a live session cap."""

from __future__ import annotations

from pathlib import Path

from scripts.lib import merge_budget
from scripts.lib.action_binding import binding, git_out, pr_number_for_branch
from scripts.lib.authority_object import read_authority
from scripts.lib.authority_permits import permits


def reserve(session: str, number: str, bind: dict[str, str] | None) -> tuple[str, Path | None]:
    """Reserve one merge while holding the session lock exactly once."""
    if bind is None:
        return "binding_unknown", None
    with merge_budget.lock(session) as acquired:
        if not acquired:
            return "budget_lock_unavailable", None
        verdict = permits(session, "merge")
        if not verdict["allow"]:
            return str(verdict["reason"]), None
        path = merge_budget.reserve(session, number, bind)
        return ("ok", path) if path else ("budget_lock_unavailable", None)


def direct(
    session: str,
    number: str,
    cwd: str,
    target: str | None,
    verified_sha: str | None,
) -> tuple[bool, str, Path | None]:
    """Reserve a direct merge when live authority exists; bind its requested PR and verified head."""
    if not read_authority(session):
        return False, "no_authority", None
    branch = git_out(cwd, "branch", "--show-current") if target == "auto" else target
    if branch and not branch.isdigit() and pr_number_for_branch(branch, cwd) != number:
        return True, "binding_unknown", None
    bind = binding("merge", f"python3 scripts/merge.py {target or number}", cwd)
    if bind and verified_sha and bind["sha"] != verified_sha:
        return True, "sha_mismatch", None
    code, path = reserve(session, number, bind)
    return True, code, path
