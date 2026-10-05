"""Worktree identity for the verification-volume ceiling (byte-identical Claude/Codex copy; stdlib only).

The counter key is sha1(realpath(git common dir) + realpath(toplevel)): a renamed branch keeps its count and two
repositories that share a branch name do not share one. The count is also mirrored into a progress.json work unit
whose `worktree` is this toplevel (`work_units[u].verification[field]`); the file counter works without it.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from typing import Any, cast


def worktree_key(cwd: str) -> tuple[str, str]:
    """Return (hex digest, realpath of the toplevel); outside a repository the key is the realpath of cwd."""
    top = os.path.realpath(cwd)
    common = ""
    try:
        done = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        done = None
    lines = done.stdout.split("\n") if done is not None and done.returncode == 0 else []
    if len(lines) >= 2 and lines[0] and lines[1]:
        common, top = os.path.realpath(os.path.join(cwd, lines[0])), os.path.realpath(lines[1])
    return hashlib.sha1((common + top).encode()).hexdigest(), top


def mirror(state: dict[str, Any], top: str, field: str, total: int) -> bool:
    """Set verification[field] = total on every work unit whose worktree is `top`; True when one matched."""
    units: object = state.get("work_units")
    if not isinstance(units, dict):
        return False
    hit = False
    for raw in cast(dict[str, object], units).values():
        if not isinstance(raw, dict):
            continue
        unit = cast(dict[str, Any], raw)
        worktree = unit.get("worktree")
        if isinstance(worktree, str) and worktree and os.path.realpath(worktree) == top:
            if not isinstance(unit.get("verification"), dict):
                unit["verification"] = {}
            unit["verification"][field] = total
            hit = True
    return hit
