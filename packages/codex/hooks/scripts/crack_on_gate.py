#!/usr/bin/env python3
"""Enforce a session-scoped authority object; the phrase 'crack on' only prints how to grant one."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from hook_common import (
    append_trace_row,
    authority_path,
    deny,
    log,
    payload_object,
    read_input,
    safe_id,
    session_dir,
    text_field,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib.authority_object import read_authority, validate  # noqa: E402

CRACK_ON = re.compile(r"(^|[^a-z0-9])crack[\s-]+on([^a-z0-9]|$)", re.IGNORECASE)
AUTHORITY_CLI = Path(__file__).resolve().parents[2] / "scripts" / "authority.py"
HINT = (
    "[crack-on] no authority granted: the phrase alone grants nothing. To grant, the user invokes "
    "$coderails-codex:authorize or runs python3 {cli} grant --session {session} --max-prs N"
)
DENIAL = (
    "Crack-on is active for this session (expiring, revocable authority). Continue autonomously within the user's "
    "scope, or end with a clear report if the work is genuinely blocked. Merge still needs explicit approval."
)
LEGACY_DENIAL = (
    "Crack-on is active (legacy flag, no expiry; support is removed in the next release). "
    "Clear it with: rm {flag}  -- or grant an expiring, revocable authority with $coderails-codex:authorize."
)


def stored(session_id: str) -> tuple[dict[str, Any], bool]:
    """This session's authority file as (object, corrupt); corrupt means unparseable or not a JSON object."""
    path = authority_path(session_id)
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8")) if path else None
    except OSError:
        return {}, False
    except ValueError:
        return {}, True
    if raw is None:
        return {}, False
    return (cast("dict[str, Any]", raw), False) if isinstance(raw, dict) else ({}, True)


def main() -> int:
    """Hint on the crack-on phrase (never grant); deny native human-input requests while an authority is live."""
    payload = payload_object(read_input())
    session_id = text_field(payload, "session_id")
    if not safe_id(session_id):
        return 0
    event = text_field(payload, "hook_event_name")
    if event == "UserPromptSubmit":
        if CRACK_ON.search(text_field(payload, "prompt")) and read_authority(session_id) is None:
            append_trace_row("crack_on", "ignored", "authority_phrase_ignored", session_id)
            log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=0 phrase_ignored=1")
            hint = HINT.format(cli=AUTHORITY_CLI, session=session_id)
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": hint}}))
        return 0
    if event != "PreToolUse" or text_field(payload, "tool_name") != "request_user_input":
        return 0
    obj = read_authority(session_id)
    data, corrupt = stored(session_id)
    if obj is None and corrupt:
        append_trace_row("crack_on", "ignored", "authority_corrupt_ignored", session_id)
    if obj is not None:
        append_trace_row("crack_on", "blocked", "authority_deny", session_id)
        log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=request_user_input denied=1")
        deny(DENIAL)
    elif data.get("session_id") == session_id and validate(data, datetime.now(timezone.utc)) == ["expired"]:
        append_trace_row("crack_on", "allowed", "authority_expired_allow", session_id)
    else:
        directory = session_dir(session_id)
        if directory is not None and (directory / "crack_on_active").is_file():
            append_trace_row("crack_on", "blocked", "crack_on_legacy_flag", session_id)
            log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=request_user_input denied=1 legacy=1")
            deny(LEGACY_DENIAL.format(flag=directory / "crack_on_active"))
    return 0


if __name__ == "__main__":
    try:
        from lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("crack_on_gate", main))
