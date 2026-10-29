"""Prefetch typed dispatch inputs before entering either provider's progress lock."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import graph_contract
from graph_lessons import needed


def prefetch(
    path: Path, push_script: Path, loader: Callable[[Path], dict[str, Any]], authorization: bool = False
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Read current lessons only for assigned units or a prior lesson-bearing dispatch."""
    preview = loader(path)
    snapshot = (
        graph_contract.current_lessons(path, push_script, preview["session_id"])
        if needed(preview, authorization)
        else None
    )
    return preview, snapshot


def check_revision(preview: dict[str, Any], current: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
    """Refuse an identity or revision change after the pre-lock lesson read."""
    if snapshot is not None and any(current[key] != preview[key] for key in ("session_id", "loop_id", "revision")):
        raise graph_contract.DispatchDeniedError("dispatch_lessons_stale", "graph changed during lessons query")
