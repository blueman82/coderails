"""Bind one assigned checkout and unit manifest to a source Git head."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, cast


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a bounded Git read and convert process failures to a typed source refusal."""
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"cannot inspect assigned checkout: {error}") from error


def source_binding(worktree: str, manifest: list[str]) -> dict[str, str]:
    """Bind the canonical assigned checkout, its current Git head, and the unit manifest."""
    root = Path(worktree).resolve()
    if not root.is_dir():
        raise ValueError("--worktree must name an existing directory")
    result = _git(root, "rev-parse", "HEAD")
    head = result.stdout.strip() if result.returncode == 0 else None
    if head is None or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", head) is None:
        raise ValueError("--worktree must name a Git checkout with a HEAD commit")
    top = _git(root, "rev-parse", "--show-toplevel")
    if top.returncode or Path(top.stdout.strip()).resolve() != root:
        raise ValueError("--worktree must name the Git checkout root")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode or status.stdout.strip():
        raise ValueError("--worktree must be clean before worker launch")
    payload = {"worktree": str(root), "manifest": manifest}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"source_manifest_sha256": digest, "source_head_sha": head}


def check_binding(stored: object, contract: dict[str, Any]) -> None:
    """Check that the saved assignment and this wave still describe the same source."""
    if not isinstance(stored, dict):
        raise ValueError("unit record is missing")
    unit = cast(dict[str, Any], stored)
    worktree = unit.get("worktree")
    if worktree is None:
        if contract.get("worktree") is not None:
            raise ValueError("assigned worktree was removed")
        return
    manifest = unit.get("manifest", [])
    if not isinstance(manifest, list) or not all(isinstance(item, str) for item in cast(list[object], manifest)):
        raise ValueError("unit manifest is invalid")
    current = source_binding(str(worktree), cast(list[str], manifest))
    expected = {"worktree": str(Path(worktree).resolve()), **current}
    if unit.get("source_manifest_sha256") != current["source_manifest_sha256"] or any(
        contract.get(key) != value for key, value in expected.items()
    ):
        raise ValueError("assigned worktree or manifest changed")
