#!/usr/bin/env python3
"""Protect native configuration and source edits on main or master."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hook_common import deny, log, patch_paths, payload_object, read_input, repo_for_path, text_field

CONFIGS = {".codex/config.toml", ".codex/requirements.toml"}
ALLOWED_SUFFIXES = {".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg"}


def plugin_source(path: str) -> bool:
    """Return whether a path is native plugin instruction source."""
    skill = path.endswith("/SKILL.md") and ("/skills/" in path or path.startswith("skills/"))
    command = path.endswith(".md") and ("/commands/" in path or path.startswith("commands/"))
    return skill or command


def protected_code(path: str) -> bool:
    """Return whether a path is source rather than an allowed metadata file."""
    return Path(path).suffix not in ALLOWED_SUFFIXES and Path(path).name not in {".gitignore", "LICENSE"}


def current_branch(repo: Path) -> str:
    """Return the current branch, or an empty value when Git cannot report one."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "branch", "--show-current"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def main() -> int:
    """Deny protected edits on main or master while allowing feature work."""
    payload = payload_object(read_input())
    cwd = Path(text_field(payload, "cwd") or os.getcwd())
    for file_path in patch_paths(payload):
        if file_path in CONFIGS or any(file_path.endswith(f"/{config}") for config in CONFIGS):
            deny(
                f"Blocked edit to '{file_path}'. Native Codex permission and hook configuration must be "
                "changed by the owner outside the agent."
            )
            return 0
        source = plugin_source(file_path)
        if not source and not protected_code(file_path):
            continue
        repo = repo_for_path(Path(file_path) if Path(file_path).is_absolute() else cwd / file_path)
        if repo is None or (branch := current_branch(repo)) not in {"main", "master"}:
            continue
        if source and not (repo / ".codex-plugin" / "plugin.json").is_file():
            continue
        log(f"hook=no_edit_on_main decision=deny branch={branch} file={file_path}")
        deny(
            f"Blocked edit to '{file_path}'. Source files cannot be edited directly on '{branch}'. "
            "Switch to a feature branch, then apply the patch there."
        )
        return 0
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("no_edit_on_main", main))
