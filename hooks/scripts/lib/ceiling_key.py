"""Worktree identity for the verification-volume ceiling (byte-identical Claude/Codex copy; stdlib only).

The counter key is sha1(realpath(git common dir) + realpath(toplevel)): a renamed branch keeps its count and two
repositories that share a branch name do not share one. The count is also mirrored into a progress.json work unit
whose owned running wave registers this toplevel (`work_units[u].verification[field]`).
The file counter works without it.
"""

from __future__ import annotations

import hashlib
import os
import re
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


def legacy_key(cwd: str, target: str, *, codex: bool = False) -> str:
    """Return the pre-worktree counter filename for the selected branch."""
    try:
        branch = (
            subprocess.run(
                ["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True, check=False
            ).stdout.strip()
            or "(no-branch)"
        )
    except OSError:
        branch = "(no-branch)"
    slug = branch.replace("/", "-")
    if codex:
        slug = slug.replace(" ", "-")
    return f"{slug}__{target}.count"


def mirror(state: dict[str, Any], top: str, field: str, total: int, session: str, loop: str) -> bool:
    """Mirror only one worktree unit registered in this exact session's live current wave."""
    if not session or not loop or state.get("schema_version") != 3 or state.get("status") != "in-progress":
        return False
    if state.get("session_id") != session or state.get("loop_id") != loop:
        return False
    units, graph = state.get("work_units"), state.get("graph")
    if not isinstance(units, dict) or not isinstance(graph, dict):
        return False
    graph = cast(dict[str, Any], graph)
    wave, nodes = graph.get("active_wave"), graph.get("nodes")
    if not isinstance(wave, dict) or not isinstance(nodes, dict):
        return False
    wave, nodes = cast(dict[str, Any], wave), cast(dict[str, Any], nodes)
    if not isinstance(wave.get("nodes"), list):
        return False
    matches: list[tuple[str, dict[str, Any]]] = []
    for identifier, raw in cast(dict[str, object], units).items():
        if not isinstance(raw, dict):
            continue
        unit = cast(dict[str, Any], raw)
        worktree = unit.get("worktree")
        if isinstance(worktree, str) and worktree and os.path.realpath(worktree) == top:
            matches.append((identifier, unit))
    if len(matches) != 1:
        return False
    identifier, unit = matches[0]
    node = f"U3[{identifier}]"
    current = nodes.get(node)
    if not re.fullmatch(r"[1-9][0-9]*", identifier) or node not in wave["nodes"]:
        return False
    if not isinstance(current, dict) or cast(dict[str, Any], current).get("status") != "running":
        return False
    if not isinstance(unit.get("verification"), dict):
        unit["verification"] = {}
    unit["verification"][field] = total
    return True
