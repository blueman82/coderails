#!/usr/bin/env python3
"""Run the opt-in repository test command before a Git commit."""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

from test_output import begin_run, finish_run

COMMIT_COMMAND = re.compile(r"(^|[\s;&|])git\s+commit(\s|$)")
TEMPFILE_ERROR = "Test gate could not create a temporary output file, so the commit is blocked."


def read_input(timeout_seconds: float = 5.0) -> str:
    """Read available stdin bytes for at most the hook's established timeout."""
    descriptor = sys.stdin.fileno()
    chunks = bytearray()
    deadline = time.monotonic() + timeout_seconds
    with suppress(OSError):
        os.set_blocking(descriptor, False)
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


def payload_object(raw_payload: str) -> dict[str, object]:
    """Decode a hook payload, treating malformed input as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def command_for(payload: dict[str, object]) -> str:
    """Return the requested Bash command, or an empty string."""
    tool_input = payload.get("tool_input")
    typed_tool_input = cast(dict[str, object], tool_input) if isinstance(tool_input, dict) else {}
    command = typed_tool_input.get("command")
    return command if isinstance(command, str) else ""


def repo_for(cwd: str) -> Path | None:
    """Return the Git root for cwd, or none when it is not a repository."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return None
    root = result.stdout.strip()
    return Path(root) if result.returncode == 0 and root else None


def configured_command(repo_root: Path) -> str:
    """Read the first trusted Git-metadata test-command line, if configured."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-path", "coderails/test_command"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return ""
    if result.returncode != 0 or not (raw_path := result.stdout.strip()):
        return ""
    config_path = Path(raw_path)
    if not config_path.is_absolute():
        config_path = repo_root / config_path
    try:
        return config_path.read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError):
        return ""


def deny(reason: str) -> None:
    """Emit the native PreToolUse denial envelope."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    with suppress(ImportError):  # telemetry must never be able to break the hook
        from lib.hook_telemetry import mark_deny

        mark_deny()


def main() -> int:
    """Run the trusted command for Git commits and deny a failed command."""
    payload = payload_object(read_input())
    command = command_for(payload)
    if not COMMIT_COMMAND.search(command):
        return 0
    raw_cwd = payload.get("cwd")
    repo_root = repo_for(raw_cwd if isinstance(raw_cwd, str) and raw_cwd else os.getcwd())
    if repo_root is None or not (test_command := configured_command(repo_root)):
        return 0
    try:
        run = begin_run("codex", repo_root, test_command)
    except OSError:
        deny(TEMPFILE_ERROR)
        return 0
    try:
        with (run / "output.log").open("wb") as output_file:
            result = subprocess.run(
                ["/bin/bash", "-c", test_command],
                cwd=repo_root,
                check=False,
                stderr=subprocess.STDOUT,
                stdout=output_file,
            )
        notice = finish_run(run, result.returncode)
        if result.returncode != 0:
            deny(f"Test gate failed for: {test_command}\n\n{notice}")
    except (OSError, ValueError):
        deny("Test output could not be captured or recorded; commit blocked.")
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("test_gate", main))
