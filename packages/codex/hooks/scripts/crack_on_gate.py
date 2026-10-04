#!/usr/bin/env python3
"""Honor a user's crack-on request without offering human-input controls."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from hook_common import (
    append_trace_row,
    authority_path,
    authority_state,
    deny,
    log,
    payload_object,
    read_input,
    safe_id,
    session_dir,
    text_field,
    write_authority,
)

CRACK_ON = re.compile(r"(^|[^a-z0-9])crack\s+on([^a-z0-9]|$)", re.IGNORECASE)
QUOTED = re.compile(r'"[^"]*"|\u201c[^\u201d]*\u201d|`[^`]*`')
TTL = timedelta(hours=24)
DENIAL = (
    "Crack-on is active for this session (expiring, revocable authority). Continue autonomously within the user's "
    "scope, or end with a clear report if the work is genuinely blocked. Merge still needs explicit approval."
)
LEGACY_DENIAL = (
    "Crack-on is active (legacy flag, no expiry; support is removed in the next release). "
    "Clear it with: rm {flag}  -- or say crack on again for an expiring, revocable authority."
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


def grant(session_id: str) -> dict[str, object] | None:
    """Return this session's live authority, writing a fresh 24h one when none is live; None on failure."""
    state, existing = authority_state(session_id)
    if state == "live":
        return existing
    path = authority_path(session_id)
    obj: dict[str, object] = {
        "authority_id": str(uuid.uuid4()),
        "loop_id": os.environ.get("CLAUDE_LOOP_ID") or None,
        "session_id": session_id,
        "scope": ["autonomous_decisions"],
        "denied": ["destructive_shell"],
        "max_prs": 0,
        "expires_at": (datetime.now(timezone.utc) + TTL).isoformat(timespec="seconds"),
        "revocable": True,
        "approval_required_for": ["merge"],
    }
    if path is None or not write_authority(path, obj):
        return None
    append_trace_row("crack_on", "granted", "authority_granted", session_id)
    return obj


def main() -> int:
    """Grant an expiring authority on crack-on prompts and deny native human-input requests while it is live."""
    payload = payload_object(read_input())
    session_id = text_field(payload, "session_id")
    if not safe_id(session_id):
        return 0
    event = text_field(payload, "hook_event_name")
    if event == "UserPromptSubmit":
        if not invoked(text_field(payload, "prompt")):
            return 0
        obj = grant(session_id)
        if obj is None:
            log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=0 err=write_failed")
            return 0
        log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=1")
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": (
                            f"[crack-on] authority {obj['authority_id']} granted: scope={obj['scope']} "
                            f"denied={obj['denied']} expires {obj['expires_at']}; request_user_input is denied until "
                            f"then; merge still needs explicit approval. "
                            f"Revoke: python3 scripts/authority.py revoke --session {session_id}"
                        ),
                    }
                }
            )
        )
        return 0
    if event != "PreToolUse" or text_field(payload, "tool_name") != "request_user_input":
        return 0
    state, obj = authority_state(session_id)
    if state == "foreign":
        append_trace_row("authority", "refused", "authority_refused_foreign", session_id)
    if state == "live":
        append_trace_row("crack_on", "blocked", "authority_deny", session_id)
        log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=request_user_input denied=1")
        deny(DENIAL)
    elif state == "expired":
        append_trace_row("crack_on", "allowed", "authority_expired_allow", session_id)
    else:
        directory = session_dir(session_id)
        if directory is not None and (directory / "crack_on_active").is_file():
            append_trace_row("crack_on", "blocked", "crack_on_legacy_flag", session_id)
            log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=request_user_input denied=1 legacy=1")
            deny(LEGACY_DENIAL.format(flag=directory / "crack_on_active"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
