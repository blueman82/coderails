"""Validate the static assigned-worktree and manifest binding without reading source HEAD."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast


def digest(worktree: str, manifest: list[str]) -> str:
    """Hash the canonical assignment using the same bytes at dispatch and publication."""
    payload = {"worktree": str(Path(worktree).resolve()), "manifest": manifest}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(record: dict[str, Any]) -> None:
    """Refuse missing or changed static authority; publication may have dirty source or a later HEAD."""
    worktree, manifest = record.get("worktree"), record.get("manifest")
    if (
        not isinstance(worktree, str)
        or not Path(worktree).is_absolute()
        or not isinstance(manifest, list)
        or not all(isinstance(item, str) for item in cast(list[object], manifest))
        or record.get("source_manifest_sha256") != digest(worktree, cast(list[str], manifest))
    ):
        raise ValueError("unit source-manifest binding is missing or changed")
