#!/usr/bin/env python3
"""Deny protected source edits on main or master."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import (
    RESOURCE_ERRNOS,
    RESOURCE_MESSAGE,
    HostResourceError,
    deny,
    log,
    read_payload_strict,
)
from hooks.scripts.lib import protected_paths
from hooks.scripts.lib.trace_row import append_row

try:
    from hooks.scripts.lib.hook_telemetry import note_child
except ImportError:  # telemetry must never be able to break the hook

    def note_child(hook: str, returncode: int) -> None:
        """Telemetry unavailable: no-op."""


def run_git(probe: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run git in probe; resource exhaustion raises HostResourceError, any other OSError propagates."""
    try:
        return subprocess.run(["git", "-C", str(probe), *arguments], capture_output=True, text=True, check=False)
    except OSError as error:
        if error.errno in RESOURCE_ERRNOS:
            raise HostResourceError(error.errno, RESOURCE_MESSAGE) from error
        raise


def main() -> int:
    """Deny protected source edits from a main or master checkout; fail closed on host exhaustion."""
    try:
        return check()
    except HostResourceError:
        deny(RESOURCE_MESSAGE)  # fail closed: a gate that cannot read or probe must not allow the edit
        return 0


def check() -> int:
    """Decide one payload."""
    payload = read_payload_strict()
    data = payload.get("tool_input")
    if not isinstance(data, dict):
        return 0
    name_value = data.get("file_path")
    if not isinstance(name_value, str):
        return 0
    name = name_value
    try:
        policy: dict[str, list[str]] | None = protected_paths.load()
    except ValueError:  # fail closed on main below; owner permission files stay denied everywhere
        policy = None
    files = policy["settings_files"] if policy else protected_paths.FALLBACK_SETTINGS
    if protected_paths.is_settings(name, [f for f in files if f.startswith(".claude/")]):
        deny(f"Blocked: editing the Claude Code permission file ({name}).")
        return 0
    source = policy is not None and protected_paths.is_plugin_source(name, policy)
    if policy is not None and not source and protected_paths.is_document(name, policy):
        return 0
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) else os.getcwd()
    path = Path(name) if Path(name).is_absolute() else Path(cwd) / name
    probe = path.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    result = run_git(probe, "branch", "--show-current")
    note_child("no_edit_on_main", result.returncode)
    branch = result.stdout.strip()
    if branch not in {"main", "master"}:
        return 0
    if source:
        root = run_git(probe, "rev-parse", "--show-toplevel").stdout.strip()
        if not root or not (Path(root) / ".claude-plugin/plugin.json").is_file():
            return 0
    log(f"hook=no_edit_on_main decision=deny branch={branch} file={name}")
    if policy is None:
        append_row("argv", "denied", protected_paths.UNREADABLE, str(payload.get("session_id") or "?"))
        deny(f"Blocked: {protected_paths.UNREADABLE}; edit of '{name}' on '{branch}' refused until it is repaired.")
        return 0
    deny(f"Blocked: editing a source file ({name}) directly on '{branch}'. Use an isolated worktree and branch first.")
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("no_edit_on_main", main))
