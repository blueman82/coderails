#!/usr/bin/env python3
"""Run one Codex work unit from a JSON request; no host-specific imports."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


def dispatch(command: Sequence[str], cwd: str | None = None) -> tuple[str, str]:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("command must be a non-empty string array")
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    return ("done" if result.returncode == 0 else "failed", result.stdout + result.stderr)
