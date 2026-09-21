#!/usr/bin/env python3
"""Behavioural coverage for agent_model_routing_nudge.py."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parent.parent / "agent_model_routing_nudge.py"


def run(payload: dict[str, object], log_path: Path) -> tuple[int, str]:
    """Run the hook with an isolated log and return its status/output."""
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "CLAUDE_DISCIPLINE_LOG": str(log_path)},
    )
    return result.returncode, result.stdout


def payload(description: str, prompt: str, model: str | None = None) -> dict[str, object]:
    """Build an Agent PreToolUse payload with an optional model override."""
    tool_input: dict[str, object] = {"description": description, "prompt": prompt}
    if model:
        tool_input["model"] = model
    return {"tool_name": "Agent", "tool_input": tool_input}


def expect(log_path: Path, value: dict[str, object], model: str) -> None:
    """Assert a successful hook response contains only the requested suggestion."""
    status, output = run(value, log_path)
    assert status == 0, output
    if model:
        decoded: Any = json.loads(output)
        assert model in decoded["hookSpecificOutput"]["additionalContext"]
        assert "permissionDecision" not in output
    else:
        assert not output


def main() -> int:
    """Run routing cases that preserve the advisory-only hook contract."""
    with tempfile.TemporaryDirectory(prefix="coderails-model-routing.") as scratch:
        log_path = Path(scratch) / "discipline.log"
        expect(log_path, payload("Rename variables", "Format this boilerplate"), "haiku")
        expect(log_path, payload("Design auth", "Redesign the architecture"), "opus")
        expect(log_path, payload("Rename variables", "Rename foo", "haiku"), "")
        expect(log_path, payload("Redesign and rename", "Architecture and boilerplate"), "")
        expect(log_path, {"tool_name": "Bash", "tool_input": {}}, "")
    print("agent_model_routing_nudge_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
