#!/usr/bin/env python3
"""Render the pinned sandbox policy with JSON-safe path substitution."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, cast


def substitute(value: object, replacements: dict[str, str]) -> object:
    """Recursively replace placeholders in string values without altering JSON syntax."""
    if isinstance(value, str):
        for placeholder, replacement in replacements.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, list):
        return [substitute(item, replacements) for item in cast(list[object], value)]
    if isinstance(value, dict):
        return {key: substitute(item, replacements) for key, item in cast(dict[str, object], value).items()}
    return value


def render_settings(worktree: str, scratch: str, primary_git: str, out_path: str) -> None:
    """Validate inputs and render the existing allow/deny policy unchanged."""
    for label, value in (("worktree", worktree), ("scratch", scratch), ("primary_git", primary_git)):
        if not Path(value).is_absolute():
            raise ValueError(f"{label} must be an absolute path, got: {value}")
        if not Path(value).is_dir():
            raise ValueError(f"{label} is not an existing directory: {value}")
    if platform.system() == "Darwin" and not shutil.which("rg"):
        raise ValueError("ripgrep (rg) not found — srt needs it on macOS for deny-path detection")
    home = os.environ.get("HOME")
    if not home:
        raise ValueError("HOME must be set")
    temporary = os.environ.get("TMPDIR", "/tmp").removesuffix("/")
    project_state = Path(f"/private/tmp/claude-{os.getuid()}") / worktree.replace("/", "-")
    project_state.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).with_name("srt-settings.json.template")
    stripped = "\n".join(line for line in template.read_text().splitlines() if not line.lstrip().startswith("//"))
    data: Any = json.loads(stripped)
    replacements = {
        "%%WORKTREE%%": worktree,
        "%%SCRATCH%%": scratch,
        "%%PRIMARY_GIT%%": primary_git,
        "%%HOME%%": home,
        "%%TMPDIR%%": temporary,
        "%%CLAUDE_PROJECT_STATE%%": str(project_state),
    }
    rendered = json.dumps(substitute(data, replacements), indent=2, ensure_ascii=False)
    if "%%" in rendered:
        raise ValueError("unsubstituted placeholder(s) remain")
    Path(out_path).write_text(rendered + "\n")


def main(arguments: list[str] | None = None) -> int:
    """Render one policy file and print its path on success."""
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 4:
            raise ValueError(f"expected 4 args (worktree scratch primary_git out_path), got {len(arguments)}")
        render_settings(*arguments)
        print(arguments[3])
        return 0
    except (OSError, ValueError) as error:
        print(f"render-settings: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
