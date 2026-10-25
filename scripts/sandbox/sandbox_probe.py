#!/usr/bin/env python3
"""Probe allowlisted and forbidden writes (and the credential environment) to distinguish real sandbox containment.

Run from the worker's cwd: `sandbox_probe.py <workdir> [--primary-git DIR] [--real-home DIR]`. The inside write must
succeed; every forbidden target must fail: <real HOME>/.sandbox-escape-probe, <real HOME>/.claude.json, the parent of
the primary repository, and <primary .git>/refs/heads/main. GH_TOKEN/GITHUB_TOKEN must not be in the environment.
Existing targets are only opened for append (zero bytes written), so a probe that escapes still corrupts nothing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def probe_write(path: Path) -> bool:
    """Open `path` for append without changing it; report whether that worked. A file this created is removed."""
    existed = path.exists()
    try:
        with path.open("ab"):
            pass
    except OSError:
        return False
    if not existed:
        path.unlink()
    return True


def probe(worktree: Path, primary_git: Path | None = None, real_home: Path | None = None) -> int:
    """Require an inside write and denial at every forbidden target; flag leaked credentials. Returns 0, 1 or 2."""
    if not worktree.is_dir():
        raise ValueError(f"worktree is not an existing directory: {worktree}")
    if primary_git is None:
        result = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ValueError(f"worktree is not inside a git repo: {result.stderr.strip()}")
        primary_git = Path(result.stdout.strip())
    home = real_home or Path(os.environ["HOME"])
    inside = worktree / ".sandbox-probe"
    if not probe_write(inside):
        raise ValueError(f"inside write to {inside} failed — worktree should be allowlisted")
    targets = (
        home / ".sandbox-escape-probe",
        home / ".claude.json",
        primary_git.parent.parent / "escape-probe",
        primary_git / "refs/heads/main",
    )
    escaped = [str(target) for target in targets if probe_write(target)]
    if escaped:
        print(f"sandbox-probe: write succeeded at {'; '.join(escaped)} (not sandboxed?)", file=sys.stderr)
        return 2
    leaked = [name for name in ("GH_TOKEN", "GITHUB_TOKEN") if os.environ.get(name)]
    if leaked:
        print(f"sandbox-probe: {', '.join(leaked)} present in the worker environment", file=sys.stderr)
        return 2
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Return zero only for a discriminating containment probe."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worktree")
    parser.add_argument("--primary-git", default=None, help="the primary repository's .git (default: git-common-dir)")
    parser.add_argument("--real-home", default=None, help="the owner's HOME (default: $HOME)")
    try:
        args = parser.parse_args(sys.argv[1:] if arguments is None else arguments)
        return probe(
            Path(args.worktree),
            Path(args.primary_git) if args.primary_git else None,
            Path(args.real_home) if args.real_home else None,
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"sandbox-probe: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
