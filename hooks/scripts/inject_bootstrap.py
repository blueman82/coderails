#!/usr/bin/env python3
"""SessionStart hook: inject the compact context manifest (lib/context_manifest.py) into every session.

Also nudges toward `/coderails:init` when a legacy `.claude/workflow.config.yaml`
or `.codex/workflow.config.yaml` is found between the session cwd and its git
root, and no canonical `.coderails/workflow.config.yaml` supersedes it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.context_manifest import session_manifest  # noqa: E402
from hooks.scripts.lib.hook_telemetry import note_child  # noqa: E402

MIGRATION_NUDGE = (
    "\n\nLegacy Coderails workflow configuration found. "
    "Run /coderails:init to migrate it to .coderails/workflow.config.yaml."
)


def resolve_plugin_root() -> Path:
    """Return CLAUDE_PLUGIN_ROOT if set, else the directory two levels above this script."""
    env_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parent.parent.parent


def read_stdin_payload() -> str:
    """Read the hook's stdin JSON payload, swallowing any read error."""
    try:
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def parse_payload(payload: str) -> dict[str, object]:
    """Parse the stdin payload as a JSON object, degrading to {} on any mismatch."""
    try:
        data: object = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return cast(dict[str, object], data)
    return {}


def string_field(data: dict[str, object], key: str) -> str:
    """Return data[key] if it's a string, else ""."""
    value = data.get(key)
    return value if isinstance(value, str) else ""


def git_show_toplevel(cwd: str) -> str:
    """Return the git top-level directory for cwd, or "" if not inside a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    note_child("inject_bootstrap", result.returncode)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def realpath_or_empty(path_str: str) -> str:
    """Return the resolved real path of path_str if it's a directory, else ""."""
    path = Path(path_str)
    if not path.is_dir():
        return ""
    return str(path.resolve())


def has_legacy_config(directory: str) -> bool:
    """Return whether directory carries a legacy .claude/ or .codex/ workflow.config.yaml."""
    return (Path(directory) / ".claude" / "workflow.config.yaml").is_file() or (
        Path(directory) / ".codex" / "workflow.config.yaml"
    ).is_file()


def has_canonical_config(directory: str) -> bool:
    """Return whether directory carries the canonical .coderails/workflow.config.yaml."""
    return (Path(directory) / ".coderails" / "workflow.config.yaml").is_file()


def scan_for_legacy_config(start: str, git_root: str) -> bool:
    """Climb from start toward git_root looking for a legacy config.

    Stops early, returning False, at the first canonical `.coderails` config
    found on the way up (it supersedes any legacy config below it).
    """
    probe = start
    legacy_found = False
    while probe:
        if has_canonical_config(probe):
            return False
        if has_legacy_config(probe):
            legacy_found = True
        if probe == git_root or probe == "/":
            break
        probe = os.path.dirname(probe)
    return legacy_found


def compute_nudge(source_kind: str, cwd: str) -> str:
    """Return the migration nudge text, or "" if none applies."""
    if source_kind != "startup" or not cwd:
        return ""
    git_root = git_show_toplevel(cwd)
    if not git_root:
        return ""
    start = realpath_or_empty(cwd)
    if not start:
        return ""
    return MIGRATION_NUDGE if scan_for_legacy_config(start, git_root) else ""


def main() -> int:
    """Print the SessionStart hookSpecificOutput JSON and return 0."""
    raw = read_stdin_payload()
    data = parse_payload(raw)
    nudge = compute_nudge(string_field(data, "source"), string_field(data, "cwd"))
    context = session_manifest(raw, resolve_plugin_root(), "coderails") + nudge

    output = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("inject_bootstrap", main))
