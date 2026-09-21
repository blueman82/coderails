#!/usr/bin/env python3
"""Stamp and enforce a session-scoped crack-on envelope."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from hook_common import deny, log, read_payload

CRACK_ON = re.compile(r"(^|[^a-z0-9])crack\s+on([^a-z0-9]|$)", re.IGNORECASE)
DENIAL = (
    "crack-on active: human-ask suppressed; proceed autonomously. A crack-on envelope was activated "
    "by the user in this session, so AskUserQuestion is mechanically denied — make the call yourself "
    "using the envelope scope, or end the turn with a report if genuinely outside it."
)


def text(payload: dict[str, Any], name: str) -> str:
    """Return a string payload field or the established empty default."""
    value = payload.get(name)
    return value if isinstance(value, str) else ""


def flag_path(session_id: str) -> Path | None:
    """Return the session-only flag path without graph-path existence probing."""
    session_id = session_id.replace("/", "_").replace("..", "")
    if not session_id:
        return None
    base = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", Path.home() / ".coderails" / "agentic-loop"))
    return base / session_id / "crack_on_active"


def stamp(flag: Path) -> bool:
    """Write the flag, reporting only a confirmed write as stamped."""
    try:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("\n", encoding="utf-8")
    except OSError:
        return False
    return True


def main() -> int:
    """Process the UserPromptSubmit and AskUserQuestion halves of the gate."""
    payload = read_payload()
    event = text(payload, "hook_event_name")
    session_id = text(payload, "session_id")
    flag = flag_path(session_id)
    if event == "UserPromptSubmit":
        if flag is not None and CRACK_ON.search(text(payload, "prompt")):
            if stamp(flag):
                log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=1")
            else:
                log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=0 err=write_failed")
        return 0
    if event == "PreToolUse" and text(payload, "tool_name") == "AskUserQuestion" and flag is not None:
        try:
            stamped = flag.is_file()
        except OSError:
            stamped = False
        if stamped:
            log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=AskUserQuestion denied=1")
            deny(DENIAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
