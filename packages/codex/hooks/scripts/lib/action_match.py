"""Vendored subset of hooks/scripts/lib/pr_workflow_match.py (operation, targets_main, guarded_segments).

Parity-tested against the Claude copy in packages/tests/test_codex_action_authority.py: change both together.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from lib.destructive_patterns import git_output

MERGE_SCRIPT = r"""(?:(?:bash|sh|python3?)\s+)?["']?(?:[^\s"']*/)?merge\.(?:py|sh)["']?(?:\s|$)"""


def operation(command: str) -> tuple[str, str, str]:
    """Return guarded operation, matched segment, and optional Git target directory."""
    if re.search(r"(^|[^-a-zA-Z0-9])(--dry-run|--help)([^-a-zA-Z0-9]|$)", command) and not re.search(
        r"(^|[;&|\s])" + MERGE_SCRIPT, command
    ):
        return "", "", ""
    if re.search(r"\bgit +merge +(--abort|--continue|--quit|--skip)\b", command):
        return "", "", ""
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        segment = segment.lstrip()
        for pattern, name in (
            (r"^gh\s+pr\s+create(?:\s|$)", "create"),
            (r"^gh\s+pr\s+merge(?:\s|$)", "merge"),
            (r"^git\s+merge(?:\s|$)", "git_merge"),
            (r"^git\s+push(?:\s|$)", "git_push"),
            ("^" + MERGE_SCRIPT, "merge"),
        ):
            if re.search(pattern, segment):
                return name, segment, ""
        if match := re.search(r"^git\s+-C\s+(\S+)\s+(merge|push)(?:\s|$)", segment):
            return f"git_{match[2]}", segment, match[1]
    return "", "", ""


def targets_main(command: str, cwd: str, target: str, name: str) -> bool:
    """Check both current branch and explicitly named protected push destinations."""
    if name not in {"git_merge", "git_push"}:
        return True
    match = re.match(r"^\s*cd\s+(\S+)\s*(&&|;)", command)
    target = target or (match[1] if match else "")
    directory = str(Path(cwd) / target) if target and not target.startswith("/") else target or cwd
    branch = git_output(directory, "branch", "--show-current") or git_output(cwd, "branch", "--show-current")
    if branch in {"main", "master"}:
        return True
    if name != "git_push":
        return False
    if re.search(r":(refs/heads/)?(main|master)([\s;&|)]|$)", command):
        return True
    match = re.search(r"\bgit(?:\s+-C\s+\S+)?\s+push\s+(.*)", command)
    return bool(match and re.search(r"(^|\s)\+?(refs/heads/)?(main|master)([\s;&|)]|$)", match[1]))


def guarded_segments(command: str, cwd: str) -> list[tuple[str, str, str]]:
    """Every guarded (merge | git_push to main) segment as (operation, segment, effective cwd).

    A leading `cd <dir>` segment moves the effective cwd for the segments after it, so the receipt hash binds the
    directory the operation really runs in. Each segment is matched on its own: a chain is one guard per segment.
    """
    found: list[tuple[str, str, str]] = []
    for segment in re.split(r"&&|\|\||[;|&\n]", command):
        segment = segment.strip()
        if move := re.match(r"^cd\s+(\S+)$", segment):
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(move[1].strip("\"'"))))
            continue
        name, matched, target = operation(segment)
        if name in {"merge", "git_push"} and targets_main(segment, cwd, target, name):
            found.append((name, matched, cwd))
    return found
