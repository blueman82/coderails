#!/usr/bin/env python3
"""Keep native apply-patch writes within the configured wiki taxonomy."""
from __future__ import annotations

import os
import sys
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib.config import settings, wiki_page_types  # noqa: E402


def configuration(cwd: Path, root: Path) -> Path | None:
    """Find the nearest project configuration up to its Git root."""
    for probe in (cwd, *cwd.parents):
        candidate = probe / ".coderails/workflow.config.yaml"
        if candidate.is_file():
            return candidate
        if probe == root:
            break
    return None


def taxonomy(cwd: Path, session: str) -> tuple[Path, Path, list[str]] | None:
    """Resolve a positively identified vault and schema, failing open on ambiguity."""
    root = repo_for_path(cwd)
    if root is None:
        return None
    config = configuration(cwd, root)
    if config is None:
        return None
    schema = root / "wiki.schema.json"
    try:
        value = str(settings(config).get("wiki_path") or "")
        if not value:
            return None
        vault = (config.parent.parent / value).resolve(strict=True)
        types, problem = wiki_page_types(schema)
        if problem:
            append_trace_row("wiki_taxonomy_gate", "failed_open", problem, session)
            return None
        sanctioned = [name + "/" for name in types]
        if sum((vault / directory).is_dir() for directory in sanctioned) < 2:
            return None
        return vault, schema, sanctioned
    except (OSError, ValueError):
        return None


def main() -> None:
    """Deny only a patch path in an identified vault's unsanctioned directory."""
    payload = payload_object(read_input())
    cwd = Path(text_field(payload, "cwd", os.getcwd()))
    resolved = taxonomy(cwd, text_field(payload, "session_id", ""))
    if resolved is None:
        return
    vault, schema, sanctioned = resolved
    for file in patch_paths(payload):
        absolute = (cwd / file).resolve()
        if repo_for_path(absolute) != vault:
            continue
        try:
            parts = absolute.relative_to(vault).parts
        except ValueError:
            continue
        if len(parts) < 2:
            continue
        topdir = parts[0] + "/"
        if topdir in sanctioned or topdir in {"raw/", ".git/", ".obsidian/", ".codex/"}:
            continue
        log(f"hook=wiki_taxonomy_gate decision=deny file={file} topdir={topdir}")
        deny(
            f"'{topdir}' is not a sanctioned wiki directory for '{file}'. "
            f"Allowed directories from {schema}: {' '.join(sanctioned)}"
        )
        return


if __name__ == "__main__":
    main()
