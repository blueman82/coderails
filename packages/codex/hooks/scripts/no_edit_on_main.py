#!/usr/bin/env python3
"""Protect native configuration and source edits on main or master."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from hook_common import (
    append_trace_row,
    deny,
    log,
    patch_paths,
    payload_object,
    read_input,
    repo_for_path,
    text_field,
)
from lib import protected_paths


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
    try:
        policy: dict[str, list[str]] | None = protected_paths.load()
    except ValueError:  # fail closed on main below; owner configuration files stay denied everywhere
        policy = None
    listed = policy["settings_files"] if policy else protected_paths.FALLBACK_SETTINGS
    configs = [f for f in listed if f.startswith(".codex/")]
    for file_path in patch_paths(payload):
        if protected_paths.is_settings(file_path, configs):
            deny(
                f"Blocked edit to '{file_path}'. Native Codex permission and hook configuration must be "
                "changed by the owner outside the agent."
            )
            return 0
        source = policy is not None and protected_paths.is_plugin_source(file_path, policy)
        if policy is not None and not source and protected_paths.is_document(file_path, policy):
            continue
        repo = repo_for_path(Path(file_path) if Path(file_path).is_absolute() else cwd / file_path)
        if repo is None or (branch := current_branch(repo)) not in {"main", "master"}:
            continue
        if source and not (repo / ".codex-plugin" / "plugin.json").is_file():
            continue
        log(f"hook=no_edit_on_main decision=deny branch={branch} file={file_path}")
        if policy is None:
            append_trace_row("argv", "denied", protected_paths.UNREADABLE, text_field(payload, "session_id"))
            deny(f"Blocked edit to '{file_path}': {protected_paths.UNREADABLE}; repair it before editing '{branch}'.")
            return 0
        deny(
            f"Blocked edit to '{file_path}'. Source files cannot be edited directly on '{branch}'. "
            "Switch to a feature branch, then apply the patch there."
        )
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
