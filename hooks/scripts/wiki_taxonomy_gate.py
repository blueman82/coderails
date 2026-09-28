#!/usr/bin/env python3
"""Reject unsanctioned top-level page types only inside a positively identified wiki."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.loop_state_common import log


def main() -> int:
    """Read live page types and fail open whenever wiki identity is ambiguous."""
    payload = read_payload()
    tool_input = payload.get("tool_input")
    file = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file, str) or not file:
        return 0
    cwd = str(payload.get("cwd") or os.getcwd())
    path = Path(file) if Path(file).is_absolute() else Path(cwd) / file
    probe = path.parent
    while not probe.is_dir() and probe != probe.parent:
        probe = probe.parent
    root = git_output(str(probe), "rev-parse", "--show-toplevel")
    if not root:
        return 0
    absolute = probe.resolve() / path.relative_to(probe)
    plugin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", "/"))
    schema = plugin / "AGENTS.md"
    try:
        source = schema.read_text()
        configuration = (plugin / ".coderails/workflow.config.yaml").read_text()
    except OSError:
        return 0
    section = re.search(r"^## Page types[^\n]*\n(.*?)(?=^## |\Z)", source, re.M | re.S)
    sanctioned = re.findall(r"`([A-Za-z0-9_-]+/)`", section[1]) if section else []
    match = re.search(r"^wiki_path:\s*(\S+)", configuration, re.M)
    wiki = match[1].strip("\"'") if match else ""
    if not sanctioned or wiki in {"", "null", "~"}:
        return 0
    vault = Path(wiki) if Path(wiki).is_absolute() else plugin / wiki
    if not vault.is_dir() or str(vault.resolve()) != root:
        return 0
    if sum((Path(root) / directory).is_dir() for directory in sanctioned) < 2:
        return 0
    try:
        relative = absolute.relative_to(root)
    except ValueError:
        return 0
    if len(relative.parts) < 2:
        return 0
    top = relative.parts[0] + "/"
    if top in {"raw/", ".git/", ".obsidian/", ".claude/", *sanctioned}:
        return 0
    deny(
        f"Blocked: '{top}' is not a sanctioned wiki page-type directory (file: {file}). "
        f"Sanctioned directories per {schema}: {' '.join(sanctioned)}. Either move this page into one of those "
        f"directories, or add '{top}' to that file's Page types table first (which then permits it automatically)."
    )
    log(f"hook=wiki_taxonomy_gate decision=deny reason=unsanctioned_dir file={file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
