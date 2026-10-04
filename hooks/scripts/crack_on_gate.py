#!/usr/bin/env python3
"""Stamp and enforce a session-scoped crack-on envelope."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, output, read_payload
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.authority_object import (
    authority_path,
    clear_legacy_flags,
    read_authority,
    safe_session,
    validate,
    write_authority,
)

CRACK_ON = re.compile(r"(^|[^a-z0-9])crack\s+on([^a-z0-9]|$)", re.IGNORECASE)
QUOTED = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d|`[^`]*`')
TTL = timedelta(hours=24)
DENIAL = (
    "crack-on active: human-ask suppressed; proceed autonomously. A crack-on authority (expires {expires}, "
    "revoke: python3 scripts/authority.py revoke --session {session}) was granted by the user in this session, "
    "so AskUserQuestion is mechanically denied: make the call yourself using the authority scope, or end the "
    "turn with a report if genuinely outside it. Merge still needs explicit approval."
)
LEGACY_DENIAL = (
    "crack-on active (legacy flag, no expiry; support is removed in the next release): AskUserQuestion is denied. "
    "Clear it with: rm {flag}  -- or say crack on again to get an expiring, revocable authority."
)


NEGATION = re.compile(
    r"^(?:don'?t|don\u2019t|dont|not|never|no|won'?t|can'?t|cannot|stop|wait|without|hold|off)$", re.IGNORECASE
)
CLAUSE_END = re.compile(r"[.!?;,:\n\u2014]")


def invoked(prompt: str) -> bool:
    """Return True for crack on outside quotes/backticks with no negation in the three words before it."""
    prompt = QUOTED.sub(" ", prompt)
    for match in CRACK_ON.finditer(prompt):
        clause = CLAUSE_END.split(prompt[: match.start()])[-1]
        if not any(NEGATION.match(word) for word in clause.split()[-3:]):
            return True
    return False


def text(payload: dict[str, Any], name: str) -> str:
    """Return a string payload field or the established empty default."""
    value = payload.get(name)
    return value if isinstance(value, str) else ""


def legacy_flag(session_id: str) -> Path | None:
    """Return the pre-authority flag path for a path-safe exact session id (migration only)."""
    path = authority_path(session_id)
    return path.with_name("crack_on_active") if path else None


def grant(session_id: str) -> dict[str, Any] | None:
    """Return this session's live authority, writing a fresh 24h one when none is valid; None on write failure."""
    existing = read_authority(session_id)
    if existing is not None:
        return existing
    path = authority_path(session_id)
    now = datetime.now(timezone.utc)
    loop_id = os.environ.get("CLAUDE_LOOP_ID") or None
    obj: dict[str, Any] = {
        "authority_id": str(uuid.uuid4()),
        "loop_id": loop_id,
        "session_id": session_id,
        "scope": ["autonomous_decisions"],
        "denied": ["destructive_shell"],
        "max_prs": 0,
        "expires_at": (now + TTL).isoformat(timespec="seconds"),
        "revocable": True,
        "approval_required_for": ["merge"],
    }
    if path is None or not write_authority(path, obj):
        append_row("crack_on", "failed_open", "authority_write_failed", session_id, loop_id)
        return None
    clear_legacy_flags(session_id)
    append_row("crack_on", "granted", "authority_granted", session_id, loop_id)
    return obj


def expired(session_id: str) -> bool:
    """True when this session's own authority file parses but is past its expiry."""
    path = authority_path(session_id)
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return False
    data = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    return data.get("session_id") == session_id and validate(data, datetime.now(timezone.utc)) == ["expired"]


def main() -> int:
    """Process the UserPromptSubmit grant and the AskUserQuestion denial."""
    payload = read_payload()
    event = text(payload, "hook_event_name")
    session_id = text(payload, "session_id")
    if not safe_session(session_id):
        return 0
    if event == "UserPromptSubmit":
        if invoked(text(payload, "prompt")):
            obj = grant(session_id)
            if obj is None:
                log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=0 err=write_failed")
                return 0
            log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=1")
            output(
                "UserPromptSubmit",
                additionalContext=(
                    f"[crack-on] authority {obj['authority_id']} granted: scope={obj['scope']} denied={obj['denied']} "
                    f"expires {obj['expires_at']}; AskUserQuestion is denied until then; merge still needs explicit "
                    f"approval. Revoke: python3 scripts/authority.py revoke --session {session_id}"
                ),
            )
        return 0
    if event == "PreToolUse" and text(payload, "tool_name") == "AskUserQuestion":
        obj = read_authority(session_id)
        loop_id = os.environ.get("CLAUDE_LOOP_ID") or None
        if obj is not None:
            append_row("crack_on", "blocked", "authority_deny", session_id, obj["loop_id"])
            log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=AskUserQuestion denied=1")
            deny(DENIAL.format(expires=obj["expires_at"], session=session_id))
        elif expired(session_id):
            append_row("crack_on", "allowed", "authority_expired_allow", session_id, loop_id)
        elif (flag := legacy_flag(session_id)) is not None and flag.is_file():
            append_row("crack_on", "blocked", "crack_on_legacy_flag", session_id, loop_id)
            log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=AskUserQuestion denied=1 legacy=1")
            deny(LEGACY_DENIAL.format(flag=flag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
