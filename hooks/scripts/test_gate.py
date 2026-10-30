#!/usr/bin/env python3
"""Run a project's opt-in test command before allowing ``git commit``."""

from __future__ import annotations

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from hooks.scripts.lib.hook_telemetry import note_child
except ImportError:  # telemetry must never be able to break the hook

    def note_child(hook: str, returncode: int) -> None:
        """Telemetry unavailable: no-op."""


from hooks.scripts.hook_common import RESOURCE_MESSAGE, HostResourceError
from hooks.scripts.hook_common import output as hook_output
from hooks.scripts.lib.argv_match import git_invocation, git_prefix
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.shell_context import invocations, opaque_execution, payload_cwd
from hooks.scripts.test_output import begin_run, finish_run


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


def configured_test_command(directory: Path = Path(".")) -> str:
    """Read the first project-local test command line, preserving the hook contract."""
    try:
        return (directory / ".claude/test_command").read_text(encoding="utf-8").splitlines()[0]
    except (IndexError, OSError):
        return ""


def deny(command: str, output: str) -> None:
    """Emit the established PreToolUse denial envelope."""
    hook_output(
        "PreToolUse",
        permissionDecision="deny",
        permissionDecisionReason=f"Test gate failed. Project test_command: {command}\n\n{output}",
    )


def _main() -> int:
    """Deny a commit only when the configured project test command fails."""
    raw = read_payload()
    if not (command := command_from(raw)):
        return 0
    payload = cast(dict[str, object], json.loads(raw))
    if opaque_execution(command, payload_cwd(payload)):
        deny("git commit", "Executable shell body exceeds the guarded parser depth.")
        return 0
    checked: set[Path] = set()
    for _, argv, cwd in invocations(command, payload_cwd(payload)):
        call = git_invocation(argv, cwd)
        if call is None or call[0] != "commit":
            continue
        prefix = git_prefix(argv, call[2])
        directory = Path(git_output(cwd, *prefix, "rev-parse", "--show-toplevel") or call[1]).resolve()
        if directory in checked:
            continue
        checked.add(directory)
        if not (test_command := configured_test_command(directory)):
            continue
        try:
            run = begin_run("claude", directory, test_command)
            with (run / "output.log").open("wb") as log_file:
                result = subprocess.run(
                    ["/bin/bash", "-c", test_command],
                    cwd=directory,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            notice = finish_run(run, result.returncode)
        except (OSError, ValueError):
            deny(test_command, "Test output could not be captured or recorded; commit blocked.")
            return 0
        note_child("test_gate", result.returncode)
        if result.returncode != 0:
            deny(test_command, notice)
            return 0
    return 0


def main() -> int:
    """Block a commit if a host resource error prevents a required Git lookup."""
    try:
        return _main()
    except HostResourceError:
        deny("git commit", RESOURCE_MESSAGE)
        return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("test_gate", main))
