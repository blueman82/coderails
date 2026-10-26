"""Claude-owned locking around independently installed pure graph semantics."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .loop_state_common import atomic_progress_update

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/agentic-loop/scripts"))
import graph_contract as graph_contract
import graph_repair as graph_repair
import graph_semantics as graph_semantics
import graph_spec as graph_spec

ROOT = Path(__file__).resolve().parents[3]


def validate_state(value: object) -> dict[str, Any]:
    """Validate current semantics, the spec's required edges and the Claude session ownership envelope."""
    state = graph_semantics.validate(value)
    for key in ("session_id", "loop_id"):
        if not isinstance(state.get(key), str) or not state[key].strip():
            raise ValueError(f"{key} must be a non-blank string")
    if state.get("status") not in {"initialising", "in-progress", "complete"}:
        raise ValueError("invalid loop status")
    graph_spec.check(state)
    graph_contract.validate_dispatch_state(state)
    graph_repair.validate_records(state)
    return state


def _trace_spec(path: Path, state: object, error: graph_spec.SpecError) -> None:
    """Leave a non-authoritative refusal row for a spec violation (the import is lazy: graph_recovery imports this)."""
    from .graph_recovery import trace

    trace(path, state if isinstance(state, dict) else {}, "refused", error.code, {}, [], "load")  # pyright: ignore


def load(path: Path) -> dict[str, Any]:
    """Read a complete current state, failing closed on corruption."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
        try:
            return validate_state(raw)
        except graph_spec.SpecError as error:
            _trace_spec(path, raw, error)
            raise
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read graph: {error}") from error


def transition(
    path: Path, transform: Callable[[dict[str, Any]], dict[str, Any]], preserve_updated_at: bool = False
) -> dict[str, Any]:
    """Read, validate, transform and replace once under the sole Claude state lock."""
    result: dict[str, Any] = {}
    errors: list[str] = []

    def update(state: dict[str, Any]) -> dict[str, Any]:
        try:
            proposed = transform(validate_state(state))
            validate_state(proposed)
            result.update(proposed)
            return proposed
        except graph_spec.SpecError as error:
            _trace_spec(path, state, error)
            errors.append(str(error))
            raise
        except ValueError as error:
            errors.append(str(error))
            raise

    if not atomic_progress_update(path, update, preserve_updated_at=preserve_updated_at):
        raise ValueError(errors[0] if errors else "graph lock or atomic update failed")
    return result


def ready_nodes(path: Path) -> list[str]:
    """Return canonical ready nodes without changing durable state."""
    return graph_semantics.ready(load(path))
