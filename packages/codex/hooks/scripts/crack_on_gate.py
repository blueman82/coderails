#!/usr/bin/env python3
"""Honor a user's crack-on request without offering human-input controls."""

from __future__ import annotations

import re

from hook_common import deny, log, payload_object, read_input, session_dir, stamp, text_field

CRACK_ON = re.compile(r"(^|[^a-z0-9])crack\s+on([^a-z0-9]|$)", re.IGNORECASE)
DENIAL = (
    "Crack-on is active for this session. Continue autonomously within the user's scope, "
    "or end with a clear report if the work is genuinely blocked."
)


NEGATION = re.compile(
    r"^(?:don'?t|don\u2019t|dont|not|never|no|won'?t|can'?t|cannot|stop|wait|without|hold|off)$", re.IGNORECASE
)
CLAUSE_END = re.compile(r"[.!?;,:\n\u2014]")


def invoked(prompt: str) -> bool:
    """Return True when the prompt says crack on without a negation among the three words before it."""
    for match in CRACK_ON.finditer(prompt):
        clause = CLAUSE_END.split(prompt[: match.start()])[-1]
        if not any(NEGATION.match(word) for word in clause.split()[-3:]):
            return True
    return False


def main() -> int:
    """Stamp crack-on prompts and deny native human-input requests while stamped."""
    payload = payload_object(read_input())
    session_id = text_field(payload, "session_id")
    directory = session_dir(session_id)
    if directory is None:
        return 0
    flag = directory / "crack_on_active"
    event = text_field(payload, "hook_event_name")
    if event == "UserPromptSubmit":
        if invoked(text_field(payload, "prompt")) and stamp(flag):
            log(f"hook=crack_on_gate event=UserPromptSubmit session={session_id} stamped=1")
        return 0
    if event != "PreToolUse" or text_field(payload, "tool_name") != "request_user_input" or not flag.is_file():
        return 0
    log(f"hook=crack_on_gate event=PreToolUse session={session_id} tool=request_user_input denied=1")
    deny(DENIAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
