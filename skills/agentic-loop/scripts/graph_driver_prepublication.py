"""Keep a finished worker attempt fixed while root publishes its PR."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast

import graph_driver_process


def validate(path: Path, claim: dict[str, Any]) -> str:
    """Reject a changed or incomplete prepublication record."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing prepublication evidence")
    data = path.read_bytes()
    try:
        parsed: object = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("invalid prepublication evidence") from error
    if not isinstance(parsed, dict):
        raise ValueError("invalid prepublication evidence")
    saved = cast(dict[str, Any], parsed)
    if set(saved) != set(claim) | {"head_at_exit"}:
        raise ValueError("invalid prepublication evidence")
    if not isinstance(saved["head_at_exit"], str) or not re.fullmatch(r"[0-9a-f]{40,64}", saved["head_at_exit"]):
        raise ValueError("invalid prepublication checkout HEAD")
    if saved["head_at_exit"] != graph_driver_process.exit_head(path.parent, claim["exit_code"]):
        raise ValueError("prepublication exit HEAD changed")
    for key, value in claim.items():
        if saved[key] != value:
            raise ValueError(f"prepublication {key.removesuffix('_sha256')} changed")
    return hashlib.sha256(data).hexdigest()


def seal(path: Path, claim: dict[str, Any]) -> None:
    """Write once, then only recheck, a finished attempt's raw facts."""
    if path.exists() or path.is_symlink():
        validate(path, claim)
        return
    head = graph_driver_process.exit_head(path.parent, claim["exit_code"])
    data = json.dumps({**claim, "head_at_exit": head}, sort_keys=True, separators=(",", ":")).encode()
    with path.open("xb") as stream:
        stream.write(data)
