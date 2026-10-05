#!/usr/bin/env python3
"""Announce Claude loop lifecycle events with per-kind debouncing."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import read_payload
from hooks.scripts.lib.agentic_loop_path import sanitise_session_id
from hooks.scripts.lib.discipline_common import stable_text
from hooks.scripts.lib.loop_state_common import load_progress, log, stable_invocations, stop_category


def announce(path: Path, session: str, kind: str, phrase: str) -> None:
    """Stamp and speak one event, keeping speech and filesystem failures advisory."""
    marker = path.parent / f"voice_announce_{kind}.last"
    now = int(time.time())
    try:
        raw = marker.read_text().strip()
        previous = int(raw) if raw.isdigit() else 0
    except OSError:
        previous = None
    prefix = f"hook=voice_announce session={session} kind={kind}"
    if previous is not None and now - previous < int(os.environ.get("CLAUDE_VOICE_DEBOUNCE_SECONDS", "60")):
        log(f"{prefix} announced=0 reason=debounced")
        return
    reason = ""
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(now))
    except OSError:
        reason = " reason=debounce_write_failed"
    log(f"{prefix} announced=1{reason}")
    binary = shutil.which("say")
    if not binary:
        log(f"{prefix} announced=0 reason=no_say_binary")
        return
    try:
        subprocess.Popen(
            [binary, phrase],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError:
        log(f"{prefix} announced=0 reason=no_say_binary")


def main() -> int:
    """Announce only active loop output; this observe-only hook always permits stop."""
    payload = read_payload()
    transcript = str(payload.get("transcript_path") or "")
    if not transcript or not Path(transcript).is_file() or payload.get("stop_hook_active") is True:
        return 0
    session = sanitise_session_id(str(payload.get("session_id") or "?"))
    count = stable_invocations(transcript)
    state = load_progress(str(payload.get("cwd") or ""), session, count)
    if not count or state.complete:
        return 0
    text, _ = stable_text(
        transcript,
        int(os.environ.get("CLAUDE_HOOK_TAIL_LINES", "300")),
        int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5")),
        float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3")),
    )
    if not text:
        log(f"hook=voice_announce session={session} reason=extract_failed")
        return 0
    category = stop_category(text)
    phrases = {
        "complete": ("complete", "Loop complete."),
        "approval-gate": ("waiting", "Loop is waiting on you."),
        "awaiting-input": ("waiting", "Loop is waiting on you."),
        "hard-stop": ("stopped", "Loop has hit a hard stop."),
    }
    if not category:
        announce(state.path, session, "stall", "Loop may have stalled.")
    elif category in phrases:
        announce(state.path, session, *phrases[category])
    return 0


if __name__ == "__main__":
    try:
        try:
            from hooks.scripts.lib.hook_telemetry import run
        except ImportError:  # telemetry must never be able to break the hook
            raise SystemExit(main()) from None
        raise SystemExit(run("voice_announce", main))
    except (OSError, ValueError, TypeError):
        log("hook=voice_announce announced=0 reason=infra_failure")
