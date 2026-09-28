#!/usr/bin/env python3
"""Probe allowlisted and forbidden writes to distinguish real sandbox containment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def probe_write(path: Path) -> bool:
    """Attempt the existing write/delete probe and report whether writing succeeded."""
    try:
        path.write_text("probe\n")
    except OSError:
        return False
    path.unlink()
    return True


def probe(worktree: Path) -> int:
    """Require an inside write and denial at both home and primary-parent boundaries."""
    if not worktree.is_dir():
        raise ValueError(f"worktree is not an existing directory: {worktree}")
    result = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"worktree is not inside a git repo: {result.stderr.strip()}")
    primary_parent = Path(result.stdout.strip()).parent.parent
    inside = worktree / ".sandbox-probe"
    if not probe_write(inside):
        raise ValueError(f"inside write to {inside} failed — worktree should be allowlisted")
    targets = (Path(os.environ["HOME"]) / ".sandbox-escape-probe", primary_parent / "escape-probe")
    escaped = [str(target) for target in targets if probe_write(target)]
    if escaped:
        print(f"sandbox-probe: write succeeded at {'; '.join(escaped)} (not sandboxed?)", file=sys.stderr)
        return 2
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Return zero only for a discriminating containment probe."""
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 1:
            raise ValueError(f"expected 1 arg (worktree), got {len(arguments)}")
        return probe(Path(arguments[0]))
    except (OSError, ValueError, KeyError) as error:
        print(f"sandbox-probe: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
