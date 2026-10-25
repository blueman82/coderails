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


def render_settings(workdir: str, scratch: str, out_path: str) -> None:
    """Validate inputs and render the scratch-only write policy for a worker whose cwd is `workdir` (in scratch)."""
    for label, value in (("workdir", workdir), ("scratch", scratch)):
        if not Path(value).is_absolute():
            raise ValueError(f"{label} must be an absolute path, got: {value}")
        if not Path(value).is_dir():
            raise ValueError(f"{label} is not an existing directory: {value}")
    if platform.system() == "Darwin" and not shutil.which("rg"):
        raise ValueError("ripgrep (rg) not found — srt needs it on macOS for deny-path detection")
    project_state = Path(f"/private/tmp/claude-{os.getuid()}") / workdir.replace("/", "-")
    project_state.mkdir(parents=True, exist_ok=True)
    template = Path(__file__).with_name("srt-settings.json.template")
    stripped = "\n".join(line for line in template.read_text().splitlines() if not line.lstrip().startswith("//"))
    data: Any = json.loads(stripped)
    replacements = {"%%SCRATCH%%": scratch, "%%CLAUDE_PROJECT_STATE%%": str(project_state)}
    rendered = json.dumps(substitute(data, replacements), indent=2, ensure_ascii=False)
    if "%%" in rendered:
        raise ValueError("unsubstituted placeholder(s) remain")
    Path(out_path).write_text(rendered + "\n")


def main(arguments: list[str] | None = None) -> int:
    """Render one policy file and print its path on success."""
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if len(arguments) != 3:
            raise ValueError(f"expected 3 args (workdir scratch out_path), got {len(arguments)}")
        render_settings(*arguments)
        print(arguments[2])
        return 0
    except (OSError, ValueError) as error:
        print(f"render-settings: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
