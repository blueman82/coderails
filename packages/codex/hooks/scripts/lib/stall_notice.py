"""Shared Stop-block notice: a state-keyed dedupe key and an automatic graph status (byte-identical per provider)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, cast

LEASE_SECONDS = 900  # graph.py recover-wave default lease; passed explicitly so the bucket and the lease agree
TIMEOUT = 2  # per graph.py call cap
DEADLINE = 4  # all status calls together; Codex Stop budget is 10s, its inspect/verify-completion are unbounded
TIMED_OUT = "timed out"
NOT_RUN = "status deadline reached"


def _quiet(message: str) -> None:
    """Default log sink."""


_MARKER = re.compile(r"\.human-approval-(.+)-(\d+)-[0-9a-f]{12}")


def marker_name(data: dict[str, Any], session: str) -> str | None:
    """Dedupe marker keyed by loop, revision, session, active wave and hard stop; None when the state has no id."""
    loop, revision, raw = data.get("loop_id"), data.get("revision"), data.get("graph")
    if not loop or not isinstance(revision, int) or isinstance(revision, bool) or not isinstance(raw, dict):
        return None
    graph = cast("dict[str, Any]", raw)
    shape = json.dumps([session, graph.get("active_wave"), graph.get("hard_stop")], sort_keys=True, default=str)
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(loop))
    return f".human-approval-{safe}-{revision}-{hashlib.sha256(shape.encode()).hexdigest()[:12]}"


def seen(state: Path, name: str) -> bool:
    """True while the marker is younger than one lease: a persistent stall re-notifies (and retries recovery) per lease.

    ponytail: the lease clock starts at the last notice, not at the worker's last activity (that lives in worker
    transcripts, readable only through graph.py); so a silent wave's first retry is at most one lease after the
    first Stop notice. Exact lease-start keying needs a wave start stamp in graph state.
    """
    marker = state.parent / name
    try:
        return marker.is_dir() and time.time() - marker.stat().st_mtime < LEASE_SECONDS
    except OSError:
        return False


def _mark(directory: Path, name: str) -> None:
    """Create or refresh a marker, then drop markers of older revisions of the same loop (bounded growth)."""
    marker = directory / name
    marker.mkdir(exist_ok=True)
    os.utime(marker)
    mine = _MARKER.fullmatch(name)
    if mine is None:
        return
    for other in directory.iterdir():
        found = _MARKER.fullmatch(other.name)
        if found and found[1] == mine[1] and int(found[2]) < int(mine[2]):
            with suppress(OSError):
                other.rmdir()


def _graph(graph: Path, deadline: float, *args: str) -> tuple[bool, str]:
    """Run one graph.py command; (ok, stdout on success, short stderr on failure). Never raises."""
    left = min(TIMEOUT, deadline - time.monotonic())
    if left <= 0:
        return False, NOT_RUN
    try:
        done = subprocess.run(
            [sys.executable, str(graph), *args], capture_output=True, text=True, check=False, timeout=left
        )
    except subprocess.TimeoutExpired:
        return False, TIMED_OUT
    except (OSError, subprocess.SubprocessError):
        return False, "graph command could not run"
    if done.returncode == 0:
        return True, done.stdout.strip()
    return False, (done.stderr.strip().splitlines() or ["no error output"])[0][:200]


def json_object(ok: bool, text: str) -> dict[str, Any] | None:
    """Decode a successful graph.py payload; None on failure or non-object output."""
    try:
        decoded: object = json.loads(text) if ok else None
    except json.JSONDecodeError:
        return None
    return cast("dict[str, Any]", decoded) if isinstance(decoded, dict) else None


def _premark(state: Path, session: str, log: Callable[[str], None]) -> None:
    """Consume the marker of the current state so our own recovery mutation does not re-notify."""
    try:
        name = marker_name(json.loads(state.read_text(encoding="utf-8")), session)
        if name:
            _mark(state.parent, name)
    except (OSError, ValueError) as error:
        log(f"stall_notice session={session} premark_failed={type(error).__name__}")


def record_notice(state: Path, session: str, name: str, log: Callable[[str], None] = _quiet) -> None:
    """Write the dedupe markers AFTER the notice is printed, so a failed or killed hook re-notifies. Never raises."""
    try:
        _mark(state.parent, name)
    except OSError as error:
        log(f"stall_notice session={session} dedupe_write_failed={type(error).__name__}")
    _premark(state, session, log)


def _names(summary: dict[str, Any], key: str) -> str:
    """Comma-joined list field; '-' when absent, empty or not a list."""
    value = summary.get(key)
    if not isinstance(value, list):
        return "-"
    return ", ".join(str(item) for item in cast("list[object]", value)) or "-"


def status_notice(graph: Path, state: Path, session: str, log: Callable[[str], None] = _quiet) -> str:
    """Compact status from `graph.py summarize`; a lost-worker wave gets one bounded `recover-wave` attempt.

    Never raises. Hooks cannot spawn agents, so a ready node only gets the exact dispatch command.
    """
    try:
        return _status(graph, state, session, log)
    except Exception as error:  # noqa: BLE001 - the required human notice must survive any failure here
        log(f"stall_notice session={session} status_failed={type(error).__name__}")
        return "Graph status unavailable: internal error; run graph.py summarize."


def _status(graph: Path, state: Path, session: str, log: Callable[[str], None]) -> str:
    deadline = time.monotonic() + DEADLINE
    ok, text = _graph(graph, deadline, "summarize", str(state))
    summary = json_object(ok, text)
    if summary is None:
        return f"Graph status unavailable: graph.py summarize failed ({text if not ok else 'unreadable output'})."
    recovery = ""
    stale = ""
    if summary.get("phase") == "waiting for worker":
        ok, text = _graph(
            graph, deadline, "recover-wave", str(state), "--session", session, "--lease-seconds", str(LEASE_SECONDS)
        )
        report = json_object(ok, text)
        if text in {TIMED_OUT, NOT_RUN} and not ok:
            recovery = (
                "recover-wave outcome unknown (timed out); run graph.py summarize"
                if text == TIMED_OUT
                else "recover-wave not attempted (status deadline reached); run graph.py summarize"
            )
        elif report is None:
            recovery = f"recover-wave refused: {text}"
        elif report.get("recovered") is True:
            recovery = "recover-wave recovered: lease expired, stale nodes respawn."
            fresh = json_object(*_graph(graph, deadline, "summarize", str(state)))
            if fresh is None:
                stale = "post-recovery status unavailable; the summary above predates recovery."
            else:
                summary = fresh
        else:
            recovery = f"recover-wave did nothing: {report.get('reason_code')}."
        log(f"stall_notice session={session} recovery={recovery}")

    lines = [
        f"Graph status: {summary.get('phase')}. {summary.get('detail')}",
        f"done: {_names(summary, 'done')}; active: {_names(summary, 'active')}; "
        f"ready: {_names(summary, 'ready')}; pending: {_names(summary, 'pending')}",
    ]
    if recovery:
        lines.append(recovery)
    if stale:
        lines.append(stale)
    elif not recovery and summary.get("phase") == "ready to dispatch":
        lines.append(f"Dispatch: python3 {graph} begin-wave {state}, then spawn the ready nodes.")
    return "\n".join(lines)
