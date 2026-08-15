#!/usr/bin/env python3
"""Small authenticated Codex CLI adapter used by live graph nodes."""

from __future__ import annotations

import subprocess
import json
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
    if not output.strip():
        return "failed", "Codex exec returned empty output"
    if result.returncode != 0:
        return "failed", output
    completed = False
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "error" or event.get("type", "").endswith(".error"):
            return "failed", output
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "error":
            return "failed", output
        completed = completed or event.get("type") == "turn.completed"
    return ("done", output) if completed else ("failed", "Codex exec missing turn.completed evidence: " + output)
