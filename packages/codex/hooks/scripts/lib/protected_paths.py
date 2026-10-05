"""Loader for policy/protected_paths.json (byte-identical Claude/Codex copy; stdlib only).

The file lists which paths the source-write and edit-on-main gates protect, so a new language is a data change.
A missing, torn or ill-shaped file raises ValueError("protected_paths_unreadable"); gates fail closed on main.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

POLICY = Path(__file__).resolve().parents[3] / "policy" / "protected_paths.json"
KEYS = ("source_extensions", "plugin_source_globs", "doc_extensions", "doc_names", "settings_files")
UNREADABLE = "protected_paths_unreadable"
# Used only when the policy is unreadable: owner permission files stay denied on every branch.
FALLBACK_SETTINGS = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".codex/config.toml",
    ".codex/requirements.toml",
)


def load(path: Path = POLICY) -> dict[str, list[str]]:
    """Return the policy lists, or raise ValueError(UNREADABLE) for any missing, torn or ill-shaped file."""
    try:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError(UNREADABLE) from None
    if not isinstance(raw, dict):
        raise ValueError(UNREADABLE)
    data = cast(dict[str, object], raw)
    result: dict[str, list[str]] = {}
    for key in KEYS:
        values = data.get(key)
        items = cast(list[object], values) if isinstance(values, list) else None
        if items is None or not all(isinstance(v, str) and v for v in items):
            raise ValueError(UNREADABLE)
        result[key] = [str(v) for v in items]
    if any(not v.startswith(".") for key in ("source_extensions", "doc_extensions") for v in result[key]):
        raise ValueError(UNREADABLE)
    return result


def glob_regex(glob: str) -> str:
    """Regex for a path glob where `*` matches one path segment."""
    return re.escape(glob).replace(r"\*", "[^/]+")


def source_regex(data: dict[str, list[str]]) -> str:
    """Regex over command text that finds a protected source file or plugin instruction file."""
    extensions = "|".join(re.escape(e[1:]) for e in data["source_extensions"]) or "(?!)"
    plugin = "|".join(glob_regex(g) for g in data["plugin_source_globs"]) or "(?!)"
    return rf"\.({extensions})([\s'\"]|$)|(^|[\s/'\"])({plugin})([\s'\"]|$)"


def is_plugin_source(path: str, data: dict[str, list[str]]) -> bool:
    """Whether the path is a plugin instruction file (skills/*/SKILL.md, commands/*.md by default)."""
    return any(re.search(rf"(^|/){glob_regex(g)}$", path) for g in data["plugin_source_globs"])


def is_document(path: str, data: dict[str, list[str]]) -> bool:
    """Whether the path is a document/config file that may be edited on main."""
    name = path.rsplit("/", 1)[-1]
    return name in data["doc_names"] or Path(path).suffix in data["doc_extensions"]


def is_settings(path: str, files: list[str] | tuple[str, ...]) -> bool:
    """Whether the path names one of the owner permission files (exact or as a trailing path)."""
    return any(path == f or path.endswith(f"/{f}") for f in files)
