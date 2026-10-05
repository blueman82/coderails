"""Typed per-session hook state in <loop dir>/<session>/hook_state.json, written through atomic_progress_update.

Shape: {schema_version: 1, ordinals: {absent_blocked: int}, arms: [{hook, ordinal}], nudged: {<hook>: true}}.
Keyed by the exact session directory, so session 'ab' can never read or suppress session 'abc'. The discipline.log
is audit output only: nothing here parses it. A missing or torn file never releases grace and is traced
`hook_state_unreadable` (outcome `missing` or `torn`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_state_common import LoopState, atomic_progress_update, log
from hooks.scripts.lib.trace_row import append_row, trace_path

SCHEMA_VERSION = 1


def state_path(session: str) -> Path | None:
    """Return <loop dir>/<session>/hook_state.json, or None for an id that is not path-local."""
    trace = trace_path(session)
    return trace.with_name("hook_state.json") if trace else None


def _shape(data: dict[str, Any]) -> dict[str, Any]:
    """Fill the typed skeleton and refuse (ValueError) any field of the wrong type, so a bad file is never rewritten."""
    data.setdefault("schema_version", SCHEMA_VERSION)
    for key, kind in (("ordinals", dict), ("arms", list), ("nudged", dict)):
        if not isinstance(data.setdefault(key, kind()), kind):
            raise ValueError(f"{key} has the wrong type")
    return data


def load_state(session: str, hook: str = "") -> dict[str, Any] | None:
    """Return the typed state, or None (traced hook_state_unreadable) when missing, torn or mistyped."""
    path = state_path(session)
    outcome = "missing"
    if path is not None and path.is_file():
        outcome = "torn"
        try:
            value: object = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return _shape(cast(dict[str, Any], value))
        except (OSError, ValueError):
            pass
    append_row(hook or "hook_state", outcome, "hook_state_unreadable", session)
    return None


def record_absent_block(state: LoopState, hook: str = "loop_state_guard") -> None:
    """Persist the invocation ordinal of an absent-state block and an arms row; fail open, never raise."""
    path = state_path(state.session)
    if path is None:
        return

    def update(data: dict[str, Any]) -> dict[str, Any]:
        data = _shape(data)
        data["ordinals"]["absent_blocked"] = state.invocations
        data["arms"].append({"hook": hook, "ordinal": state.invocations})
        return data

    atomic_progress_update(path, update, create=True)


def unstubbed_grace(state: LoopState, hook: str) -> bool:
    """Release only an absent-file block already recorded in hook_state.json at this invocation ordinal."""
    if state.path.is_file():
        return False
    data = load_state(state.session, hook)
    recorded = data["ordinals"].get("absent_blocked") if data else None
    released = isinstance(recorded, int) and not isinstance(recorded, bool) and recorded == state.invocations
    if released:
        log(f"hook={hook} session={state.session} invocations={state.invocations} unstubbed_grace=released blocked=0")
    return released


def mark_nudged(session: str, hook: str) -> bool:
    """Atomically record that `hook` nudged this session. True only for the first nudge; False when suppressed.

    An unwritable or torn state file suppresses (traced hook_state_unreadable): an advisory must not repeat unrecorded.
    """
    path = state_path(session)
    first: list[bool] = []

    def update(data: dict[str, Any]) -> dict[str, Any]:
        data = _shape(data)
        first[:] = [data["nudged"].get(hook) is not True]
        data["nudged"][hook] = True
        return data

    if path is None or not atomic_progress_update(path, update, create=True):
        append_row(hook, "torn" if path and path.is_file() else "missing", "hook_state_unreadable", session)
        return False
    append_row(hook, "nudged" if first[0] else "suppressed", "nudge_first" if first[0] else "nudge_suppressed", session)
    return first[0]
