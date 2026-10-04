"""Own native Codex graph files and validate the provider envelope."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_identity import GraphError


def load(path: Path) -> dict[str, Any]:
    """Read current graph state and validate its native owner envelope."""
    try:
        with path.open(encoding="utf-8") as handle:
            state = graph_semantics.validate(json.load(handle))
        for name in ("session_id", "loop_id"):
            value = state.get(name)
            if not isinstance(value, str) or not value.strip():
                raise GraphError(f"{name} must be a non-empty string")
        if state.get("status") not in {"initialising", "in-progress", "complete"}:
            raise GraphError("state has invalid status")
        return state
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise GraphError(f"cannot read valid state: {error}") from error


def write(path: Path, state: dict[str, Any], create: bool = False) -> None:
    """Atomically replace state while preserving its file permissions; `create` allows an absent file."""
    mode = 0o644 if create and not path.exists() else path.stat().st_mode & 0o777
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


@contextmanager
def locked(path: Path, create: bool = False) -> Generator[None, None, None]:
    """Serialize provider state mutations with a local advisory lock; `create` makes the parent directory first."""
    try:
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        with Path(f"{path}.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
    except OSError as error:
        raise GraphError(f"cannot lock state: {error}") from error


def object_value(value: object, label: str) -> dict[str, Any]:
    """Require a JSON object at the provider boundary."""
    if not isinstance(value, dict):
        raise GraphError(f"{label} must be an object")
    return cast(dict[str, Any], value)
