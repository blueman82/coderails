"""Shared Stop-block notice: a state-keyed dedupe key and an automatic graph status (byte-identical per provider)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast


def marker_name(data: dict[str, Any], session: str) -> str | None:
    """Dedupe marker keyed by loop, revision, session, active wave and hard stop; None when the state has no id."""
    loop, revision, raw = data.get("loop_id"), data.get("revision"), data.get("graph")
    if not loop or not isinstance(revision, int) or isinstance(revision, bool) or not isinstance(raw, dict):
        return None
    graph = cast("dict[str, Any]", raw)
    shape = json.dumps([session, graph.get("active_wave"), graph.get("hard_stop")], sort_keys=True, default=str)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(loop))
    return f".human-approval-{safe}-{revision}-{hashlib.sha256(shape.encode()).hexdigest()[:12]}"


def _graph(graph: Path, *args: str) -> tuple[bool, str]:
    """Run one graph.py command; (ok, trimmed output). Never raises, so the Stop block still fires."""
    try:
        done = subprocess.run(
            [sys.executable, str(graph), *args], capture_output=True, text=True, check=False, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        return False, "graph command could not run"
    return done.returncode == 0, (done.stdout if done.returncode == 0 else done.stderr).strip()[:600]


def status_notice(graph: Path, state: Path, session: str) -> str:
    """Compact status from `graph.py summarize`; a lost-worker wave gets one bounded `recover-wave` attempt.

    Hooks cannot spawn agents, so a ready node only gets the exact dispatch command. Call once per new state.
    """
    ok, text = _graph(graph, "summarize", str(state))
    try:
        decoded: object = json.loads(text) if ok else None
    except json.JSONDecodeError:
        decoded = None
    if not isinstance(decoded, dict):
        return ""
    summary = cast("dict[str, Any]", decoded)

    def names(key: str) -> str:
        return ", ".join(str(item) for item in cast("list[object]", summary.get(key) or [])) or "-"

    lines = [
        f"Graph status: {summary.get('phase')}. {summary.get('detail')}",
        f"done: {names('done')}; active: {names('active')}; ready: {names('ready')}",
    ]
    if summary.get("phase") == "waiting for worker":
        ok, text = _graph(graph, "recover-wave", str(state), "--session", session)
        lines.append(f"recover-wave ({'applied' if ok else 'refused'}): {text}")
    elif summary.get("phase") == "ready to dispatch":
        lines.append(f"Dispatch: python3 {graph} begin-wave {state}, then spawn the ready nodes.")
    return "\n".join(lines)
