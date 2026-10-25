#!/usr/bin/env python3
"""Reject unsanctioned top-level page types only inside a positively identified wiki.

Once the vault is positively identified, a missing or invalid wiki.schema.json or a rejected workflow config DENIES
the write (wiki_schema_missing / wiki_schema_invalid / config_rejected, trace outcome failed_closed). Ambiguous
identity (no config, no wiki_path, other repository, vault not a directory) still allows.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import RESOURCE_MESSAGE, HostResourceError, deny, read_payload
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.loop_state_common import log
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.config import load_config, wiki_page_types
from scripts.lib.config_strict import ConfigRejected, strict_settings


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
    try:
        root = git_output(str(probe), "rev-parse", "--show-toplevel", hook="wiki_taxonomy_gate")
    except HostResourceError:
        deny(RESOURCE_MESSAGE)
        return 0
    if not root:
        return 0
    absolute = probe.resolve() / path.relative_to(probe)
    plugin = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", "/"))
    config = plugin / ".coderails/workflow.config.yaml"
    session = str(payload.get("session_id") or "")
    wiki = str(load_config(config)[0].get("wiki_path") or "") if config.is_file() else ""
    if not wiki:
        return 0
    vault = Path(wiki) if Path(wiki).is_absolute() else plugin / wiki
    if not vault.is_dir() or str(vault.resolve()) != root:
        return 0
    schema = plugin / "wiki.schema.json"
    why = ""
    try:
        strict_settings(config, session)
        types, problem = wiki_page_types(schema)
        why = f"{schema} is {problem}"
    except ConfigRejected as error:
        types, problem, why = [], "config_rejected", str(error)
    if problem:
        append_row("wiki_taxonomy_gate", "failed_closed", problem, session)
        deny(
            f"Blocked: wiki write inside the vault while {why} ({problem}). Fix it (python3 scripts/lib/config.py "
            "resolve-config --json lists config findings) and retry."
        )
        return 0
    sanctioned = [name + "/" for name in types]
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
        f"directories, or add '{top[:-1]}' to that file's page_types first (which then permits it automatically)."
    )
    log(f"hook=wiki_taxonomy_gate decision=deny reason=unsanctioned_dir file={file}")
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("wiki_taxonomy_gate", main))
