#!/usr/bin/env python3
"""Small authenticated Codex CLI adapter used by live graph nodes."""

from __future__ import annotations

import subprocess
from collections.abc import Callable


def invoke(prompt: str, cwd: str | None = None, *, runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> tuple[str, str]:
    """Run the installed, host-authenticated Codex CLI without an app-server API."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Codex exec prompt must be non-empty")
    if cwd is None:
        raise ValueError("Codex exec cwd is required")
    command = ["codex", "exec", "--json", "--ephemeral", "-C", cwd, "-"]
    result = runner(command, cwd=cwd, input=prompt, text=True, capture_output=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    return ("done" if result.returncode == 0 else "failed", output)
