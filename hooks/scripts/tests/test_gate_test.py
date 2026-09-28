#!/usr/bin/env python3
"""Behavioural coverage for the opt-in test-gate PreToolUse hook."""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

HOOK = Path(__file__).resolve().parent.parent / "test_gate.py"


def fail(message: str) -> None:
    """Report one assertion failure and stop the focused test."""
    print(f"test_gate_test: {message}", file=sys.stderr)
    raise SystemExit(1)


def run(project: Path, command: str) -> dict[str, object]:
    """Invoke the hook from a project and return its decoded output envelope."""
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    result = subprocess.run(
        ["python3", str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
        cwd=project,
        env=os.environ | {"CODERAILS_TEST_OUTPUT_DIR": str(project / "logs")},
    )
    if result.returncode != 0:
        fail(f"hook exited {result.returncode}: {result.stderr}")
    if not result.stdout:
        return {}
    decoded: object = json.loads(result.stdout)
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def decision(project: Path, command: str) -> str:
    """Return DENY only for the hook's native denial envelope."""
    output = run(project, command)
    hook_output = output.get("hookSpecificOutput")
    typed_hook_output = cast(dict[str, object], hook_output) if isinstance(hook_output, dict) else {}
    return "DENY" if typed_hook_output.get("permissionDecision") == "deny" else "ALLOW"


def configure(project: Path, test_command: str) -> None:
    """Create the project-local opt-in test command."""
    config = project / ".claude"
    config.mkdir()
    (config / "test_command").write_text(test_command, encoding="utf-8")


def reason(project: Path, command: str) -> str:
    """Return a denial reason from a correctly-shaped hook envelope."""
    hook_output = run(project, command).get("hookSpecificOutput")
    if not isinstance(hook_output, dict):
        return ""
    typed_hook_output = cast(dict[str, object], hook_output)
    denial_reason = typed_hook_output.get("permissionDecisionReason")
    return denial_reason if isinstance(denial_reason, str) else ""


def assert_decision(project: Path, command: str, expected: str) -> None:
    """Assert the hook preserves its allow-or-deny contract."""
    actual = decision(project, command)
    if actual != expected:
        fail(f"{command!r}: expected {expected}, got {actual}")


def main() -> int:
    """Exercise no-config, passing, failing, and empty-config projects."""
    with tempfile.TemporaryDirectory(prefix="coderails-test-gate.") as scratch:
        root = Path(scratch)
        no_config = root / "no-config"
        no_config.mkdir()
        assert_decision(no_config, "git commit -m 'fix'", "ALLOW")
        assert_decision(no_config, "git status", "ALLOW")

        passing = root / "passing"
        passing.mkdir()
        configure(passing, "true\n")
        assert_decision(passing, "git commit -m 'fix'", "ALLOW")
        assert_decision(passing, "git status", "ALLOW")

        failing = root / "failing"
        failing.mkdir()
        configure(failing, "printf 'failure output\\n'; false\n")
        assert_decision(failing, "git commit -m 'fix'", "DENY")
        assert_decision(failing, "git push origin main", "ALLOW")
        denial_reason = reason(failing, "git commit -m 'fix'")
        if "Full log:" not in denial_reason:
            fail(f"denial omitted retained log location: {denial_reason!r}")
        if not any(
            gzip.decompress(path.read_bytes()) == b"failure output\n" for path in failing.rglob("output.log.gz")
        ):
            fail("complete failure output was not retained")

        empty = root / "empty"
        empty.mkdir()
        configure(empty, "")
        assert_decision(empty, "git commit -m 'fix'", "ALLOW")
    print("test_gate_test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
