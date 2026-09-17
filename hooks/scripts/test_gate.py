#!/usr/bin/env python3
"""Run a project's opt-in test command before allowing ``git commit``."""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

COMMIT_COMMAND = re.compile(r"\bgit +commit\b")
LOG_PATH = Path("/tmp/claude_test_gate.log")


def read_payload(timeout_seconds: float = 5.0) -> str:
    """Read stdin for no longer than the hook's established timeout."""
    descriptor = sys.stdin.fileno()
    chunks = bytearray()
    deadline = time.monotonic() + timeout_seconds
    try:
        os.set_blocking(descriptor, False)
    except OSError:
        return ""
    while (remaining := deadline - time.monotonic()) > 0:
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            break
        try:
            chunk = os.read(descriptor, 65536)
        except BlockingIOError:
            continue
        if not chunk:
            break
        chunks.extend(chunk)
    return chunks.decode(errors="replace")


def command_from(raw_payload: str) -> str:
    """Return the Bash command from a valid hook payload, or an empty string."""
    try:
        payload: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    typed_payload = cast(dict[str, object], payload)
    tool_input = typed_payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = cast(dict[str, object], tool_input).get("command")
    return command if isinstance(command, str) else ""


def configured_test_command() -> str:
    """Read the first project-local test command line, preserving the hook contract."""
    try:
        return Path(".claude/test_command").read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError):
        return ""


def deny(command: str, output: str) -> None:
    """Emit the established PreToolUse denial envelope."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Test gate failed. Project test_command: {command}\n\nLast 20 lines of output:\n{output}"
                    ),
                }
            }
        )
    )


def main() -> int:
    """Deny a commit only when the configured project test command fails."""
    if not (command := command_from(read_payload())) or not COMMIT_COMMAND.search(command):
        return 0
    if not (test_command := configured_test_command()):
        return 0
    try:
        with LOG_PATH.open("wb") as log_file:
            result = subprocess.run(
                ["/bin/bash", "-c", test_command], stdout=log_file, stderr=subprocess.STDOUT, check=False
            )
    except OSError:
        deny(test_command, "")
        return 0
    if result.returncode != 0:
        try:
            output_lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            output = "\n".join(output_lines[-20:]).encode()[:1500]
        except OSError:
            output = b""
        deny(test_command, output.decode(errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
