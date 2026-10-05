"""Shared Stop-block notice: a state-keyed dedupe key and an automatic graph status (byte-identical per provider)."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

LEASE_SECONDS = 900  # graph.py recover-wave default lease
TIMEOUT = 2  # per graph.py call; three calls stay well under the 10s Stop hook budget


def marker_name(data: dict[str, Any], session: str) -> str | None:
    """Dedupe marker keyed by loop, revision, session, active wave and hard stop; None when the state has no id."""
    loop, revision, raw = data.get("loop_id"), data.get("revision"), data.get("graph")
    if not loop or not isinstance(revision, int) or isinstance(revision, bool) or not isinstance(raw, dict):
        return None
    graph = cast("dict[str, Any]", raw)
    # ponytail: a running wave re-keys per lease-sized window so recover-wave retries after the lease expires
    bucket = int(time.time() // LEASE_SECONDS) if graph.get("active_wave") else None
    shape = json.dumps([session, graph.get("active_wave"), graph.get("hard_stop"), bucket], sort_keys=True, default=str)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(loop))
    return f".human-approval-{safe}-{revision}-{hashlib.sha256(shape.encode()).hexdigest()[:12]}"


def _graph(graph: Path, *args: str) -> tuple[bool, str]:
    """Run one graph.py command; (ok, stdout on success, short stderr on failure). Never raises."""
    try:
        done = subprocess.run(
            [sys.executable, str(graph), *args], capture_output=True, text=True, check=False, timeout=TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return False, "graph command could not run"
    if done.returncode == 0:
        return True, done.stdout.strip()
    return False, (done.stderr.strip().splitlines() or ["no error output"])[0][:200]


def _json(ok: bool, text: str) -> dict[str, Any] | None:
    """Decode a successful graph.py payload; None on failure or non-object output."""
    try:
        decoded: object = json.loads(text) if ok else None
    except json.JSONDecodeError:
        return None
    return cast("dict[str, Any]", decoded) if isinstance(decoded, dict) else None


def _premark(state: Path, session: str) -> None:
    """Consume the marker of the post-recovery state so our own mutation does not re-notify."""
    try:
        name = marker_name(json.loads(state.read_text(encoding="utf-8")), session)
        if name:
            (state.parent / name).mkdir(exist_ok=True)
    except (OSError, ValueError):
        pass


def status_notice(graph: Path, state: Path, session: str) -> str:
    """Compact status from `graph.py summarize`; a lost-worker wave gets one bounded `recover-wave` attempt.

    Hooks cannot spawn agents, so a ready node only gets the exact dispatch command. Call once per new state.
    """
    summary = _json(*_graph(graph, "summarize", str(state)))
    if summary is None:
        return "Graph status unavailable: graph.py summarize failed."
    recovery = ""
    if summary.get("phase") == "waiting for worker":
        ok, text = _graph(graph, "recover-wave", str(state), "--session", session)
        report = _json(ok, text)
        if report is None:
            recovery = f"recover-wave refused: {text}"
        elif report.get("recovered") is True:
            recovery = "recover-wave recovered: lease expired, stale nodes respawn."
            _premark(state, session)
            summary = _json(*_graph(graph, "summarize", str(state))) or summary
        else:
            recovery = f"recover-wave did nothing: {report.get('reason_code')}."

    def names(key: str) -> str:
        return ", ".join(str(item) for item in cast("list[object]", summary.get(key) or [])) or "-"

    lines = [
        f"Graph status: {summary.get('phase')}. {summary.get('detail')}",
        f"done: {names('done')}; active: {names('active')}; ready: {names('ready')}; pending: {names('pending')}",
    ]
    if recovery:
        lines.append(recovery)
    elif summary.get("phase") == "ready to dispatch":
        lines.append(f"Dispatch: python3 {graph} begin-wave {state}, then spawn the ready nodes.")
    return "\n".join(lines)
