#!/usr/bin/env python3
"""Resolve session-local loop state without creating or modifying files."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from hooks.scripts.lib.hook_telemetry import note_child
except ImportError:  # telemetry must never be able to break the hook

    def note_child(hook: str, returncode: int) -> None:
        """Telemetry unavailable: no-op."""


def sanitise_session_id(raw: str) -> str:
    """Keep malformed harness identifiers path-local and missing IDs independent."""
    if not raw or raw == "?":
        return f"unknown-{os.getpid()}-{time.time_ns()}"
    return raw.replace("/", "_").replace("..", "")


def resolve_path(cwd: str = "", session_id: str = "") -> Path:
    """Return canonical state, or existing state under another slug for this session."""
    cwd = cwd or os.getcwd()
    session_id = sanitise_session_id(session_id or os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    base = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    common = ""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
        )
        note_child("agentic_loop_path", result.returncode)
        if result.returncode == 0 and result.stdout.startswith("/"):
            common = result.stdout.strip()
    except OSError:
        pass
    canonical = base / (common or cwd).replace("/", "-") / session_id / "progress.json"
    if canonical.exists():
        return canonical
    try:
        candidates = sorted(path / session_id / "progress.json" for path in base.iterdir())
    except OSError:
        return canonical
    for candidate in candidates:
        if candidate.exists() and candidate.parent.is_dir():
            return candidate
    return canonical


if __name__ == "__main__":
    print(resolve_path(*(sys.argv[1:3])))
