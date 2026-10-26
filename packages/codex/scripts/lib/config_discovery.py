"""Fail-closed workflow config discovery for action gates."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path


def strict_config_path(start_dir: str | Path | None = None, *, timeout_seconds: float | None = None) -> str:
    """Return a proven config path or proven absence; raise when Git or file checks are uncertain."""
    start = Path(start_dir or Path.cwd()).resolve()
    result = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    if result.returncode:
        if "not a git repository" not in result.stderr.lower():
            raise OSError("cannot determine config repository")
        for directory in (start, *start.parents):
            try:
                (directory / ".git").stat()
            except FileNotFoundError:
                continue
            raise OSError("Git metadata exists but repository discovery failed")
        return ""
    if not result.stdout.strip():
        raise OSError("config repository path is empty")
    root = Path(result.stdout.strip()).resolve()
    current = start
    while True:
        candidate = current / ".coderails/workflow.config.yaml"
        try:
            mode = candidate.stat().st_mode
        except FileNotFoundError:
            mode = None
        if mode is not None:
            if not stat.S_ISREG(mode):
                raise OSError("workflow config path is not a regular file")
            return str(candidate)
        if current == root:
            return ""
        if current == current.parent:
            raise OSError("repository root is outside the config search path")
        current = current.parent
