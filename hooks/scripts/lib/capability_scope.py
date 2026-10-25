"""Scope questions the capability hooks share: is this session graph-bound, and is the caller a typed subagent?"""

from __future__ import annotations

from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.loop_state_common import read_state


def graph_bound(session: str, cwd: str) -> bool:
    """True when this session's progress.json carries a `graph` and names this session (a foreign file never counts)."""
    if not session or session == "?":
        return False
    state = read_state(resolve_path(cwd, session))
    return "graph" in state and state.get("session_id") == session


def has_text(value: object) -> bool:
    """A usable identity field: a non-blank string."""
    return isinstance(value, str) and bool(value.strip())
