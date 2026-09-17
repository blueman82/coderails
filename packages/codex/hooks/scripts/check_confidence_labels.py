#!/usr/bin/env python3
"""Require confidence labels on substantive native Codex final messages."""

from __future__ import annotations

import os
import re

from hook_common import continue_turn, log, payload_object, read_input, text_field

CONFIDENCE_LABEL = re.compile(r"\((verified|inferred|guess)([^)]*)?\)")


def main() -> int:
    """Block an unlabeled substantive Stop or SubagentStop message."""
    payload = payload_object(read_input())
    if payload.get("stop_hook_active") is True:
        print("{}")
        return 0
    message = text_field(payload, "last_assistant_message")
    minimum = int(os.environ.get("CODERAILS_HOOK_MIN_LEN", "200"))
    if len(message) < minimum or CONFIDENCE_LABEL.search(message):
        print("{}")
        return 0
    event = text_field(payload, "hook_event_name", "Stop")
    session_id = text_field(payload, "session_id", "unknown")
    log(f"hook=confidence_labels event={event} session={session_id} blocked=1 text_len={len(message)}")
    continue_turn(
        "Your substantive final message has no confidence labels. Add (verified), (inferred), or (guess) "
        "to the claims, then finish again."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
