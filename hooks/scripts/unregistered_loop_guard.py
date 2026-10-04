#!/usr/bin/env python3
"""Nudge dispatch-heavy Claude sessions that have not registered their loop."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import output, read_payload
from hooks.scripts.lib.agentic_loop_path import resolve_path, sanitise_session_id
from hooks.scripts.lib.discipline_common import records, tool_uses
from hooks.scripts.lib.loop_state_common import count_invocations, log


def count_dispatch_turns(transcript: str) -> tuple[int, str]:
    """Count distinct Agent-bearing messages while attributing malformed aggregate input."""
    entries = records(transcript)
    try:
        if not entries and Path(transcript).read_text().strip():
            return 0, "json_parse_error"
    except OSError:
        return 0, "read_error"
    for entry in entries:
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            return 0, "json_parse_error"
        value = cast(dict[str, Any], message).get("content")
        if value is not None and not isinstance(value, list):
            return 0, "json_parse_error"
        if isinstance(value, list) and any(not isinstance(item, dict) for item in cast(list[object], value)):
            return 0, "json_parse_error"
    identifiers = {
        str(record.get("message", {}).get("id"))
        for record in entries
        if any(tool.get("name") == "Agent" for tool in tool_uses(record))
    }
    return len(identifiers), ""


def main() -> int:
    """Emit at most one advisory for three distinct unregistered Agent turns."""
    payload = read_payload()
    transcript = str(payload.get("transcript_path") or "")
    session = sanitise_session_id(str(payload.get("session_id") or "?"))
    prefix = f"hook=unregistered_loop_guard session={session}"
    if not transcript or not Path(transcript).is_file():
        log(f"{prefix} nudged=0 reason=no_transcript")
        return 0
    turns, parse_reason = count_dispatch_turns(transcript)
    reason = ""
    if parse_reason:
        reason = parse_reason
    elif turns < 3:
        reason = "below_threshold"
    elif resolve_path(str(payload.get("cwd") or os.getcwd()), session).is_file():
        reason = "registered"
    elif count_invocations(transcript)[0]:
        reason = "skill_invoked"
    else:
        path = Path(os.environ.get("CLAUDE_DISCIPLINE_LOG", str(Path.home() / ".claude/discipline.log")))
        try:
            already = re.search(
                r"hook=unregistered_loop_guard .*session=" + re.escape(session) + r" .*nudged=1", path.read_text()
            )
        except OSError:
            already = None
        if already:
            reason = "already_nudged_this_session"
    if reason:
        log(f"{prefix} dispatch_turns={turns} nudged=0 reason={reason}")
        return 0
    log(f"{prefix} dispatch_turns={turns} nudged=1")
    output(
        "Stop",
        additionalContext=f"[unregistered-loop-guard] This session has dispatched {turns}+ separate Agent "
        "turns with no agentic-loop registration detected (no progress.json, no agentic-loop Skill invocation). "
        "If this is a multi-step loop, register it now: invoke coderails:agentic-loop and run graph.py start "
        "at the path hooks/scripts/lib/agentic_loop_path.py resolves for this session, so the loop-state guards "
        "can track it. If this is genuinely a one-off sequence of independent dispatches, no action is needed.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
