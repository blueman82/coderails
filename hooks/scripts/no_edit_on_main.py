#!/usr/bin/env python3
"""Deny protected source edits on main or master."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, read_payload
from hooks.scripts.lib.hook_telemetry import note_child

ALLOWED = {".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}


def main() -> int:
    """Deny protected source edits made from a main or master checkout."""
    payload = read_payload()
    data = payload.get("tool_input")
    if not isinstance(data, dict):
        return 0
    name_value = data.get("file_path")
    if not isinstance(name_value, str):
        return 0
    name = name_value
    if name.endswith(("/.claude/settings.json", "/.claude/settings.local.json")) or name in {
        ".claude/settings.json",
        ".claude/settings.local.json",
    }:
        deny(f"Blocked: editing the Claude Code permission file ({name}).")
        return 0
    source = (
        name.endswith("/SKILL.md")
        and "/skills/" in name
        or name.startswith("skills/")
        and name.endswith("/SKILL.md")
        or name.endswith(".md")
        and ("/commands/" in name or name.startswith("commands/"))
    )
    if not source and (Path(name).suffix in ALLOWED or Path(name).name in {".gitignore", "LICENSE"}):
        return 0
    cwd_value = payload.get("cwd")
    cwd = cwd_value if isinstance(cwd_value, str) else os.getcwd()
    path = Path(name) if Path(name).is_absolute() else Path(cwd) / name
    probe = path.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    result = subprocess.run(
        ["git", "-C", str(probe), "branch", "--show-current"], capture_output=True, text=True, check=False
    )
    note_child("no_edit_on_main", result.returncode)
    branch = result.stdout.strip()
    if branch not in {"main", "master"}:
        return 0
    if source:
        root = subprocess.run(
            ["git", "-C", str(probe), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
        ).stdout.strip()
        if not root or not (Path(root) / ".claude-plugin/plugin.json").is_file():
            return 0
    log(f"hook=no_edit_on_main decision=deny branch={branch} file={name}")
    deny(f"Blocked: editing a source file ({name}) directly on '{branch}'. Use an isolated worktree and branch first.")
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("no_edit_on_main", main))
