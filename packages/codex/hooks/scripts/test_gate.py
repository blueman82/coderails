#!/usr/bin/env python3
"""Run the opt-in repository test command before a Git commit."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

from lib.argv_match import git_invocation, git_prefix
from lib.destructive_patterns import RESOURCE_ERRNOS, git_output
from lib.shell_context import invocations, opaque_execution, payload_cwd
from test_output import begin_run, finish_run

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
    command = typed_tool_input.get("cmd", typed_tool_input.get("command"))
    return command if isinstance(command, str) else ""


def repo_for(cwd: str, prefix: list[str]) -> Path | None:
    """Return the Git root for cwd, or none when it is not a repository."""
    root = git_output(cwd, *prefix, "rev-parse", "--show-toplevel")
    return Path(root) if root else None


def configured_command(cwd: str, prefix: list[str], directory: str) -> str:
    """Read the first trusted Git-metadata test-command line, if configured."""
    raw_path = git_output(cwd, *prefix, "rev-parse", "--git-path", "coderails/test_command")
    if not raw_path:
        return ""
    config_path = Path(raw_path)
    if not config_path.is_absolute():
        config_path = Path(directory) / config_path
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


def _main() -> int:
    """Run the trusted command for Git commits and deny a failed command."""
    payload = payload_object(read_input())
    command = command_for(payload)
    if opaque_execution(command, payload_cwd(payload)):
        deny("Executable shell body exceeds the guarded parser depth.")
        return 0
    checked: set[tuple[Path, str]] = set()
    for _, argv, cwd in invocations(command, payload_cwd(payload)):
        call = git_invocation(argv, cwd)
        if call is None or call[0] != "commit":
            continue
        prefix = git_prefix(argv, call[2])
        repo_root = repo_for(cwd, prefix)
        test_command = configured_command(cwd, prefix, call[1])
        if repo_root is None or not test_command or (repo_root, test_command) in checked:
            continue
        checked.add((repo_root, test_command))
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
                return 0
        except (OSError, ValueError):
            deny("Test output could not be captured or recorded; commit blocked.")
            return 0
    return 0


def main() -> int:
    """Deny a commit when a host resource error prevents a Git lookup."""
    try:
        return _main()
    except OSError as error:
        cause = "Host resource exhaustion" if error.errno in RESOURCE_ERRNOS else "Git lookup failure"
        deny(f"{cause} prevented this hook from checking Git. Retry; the commit is blocked.")
        return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("test_gate", main))
