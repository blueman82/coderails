#!/usr/bin/env python3
"""Advise (never block) when substantive native Codex final messages carry no confidence labels."""

from __future__ import annotations

import json
import os
import re

from hook_common import append_trace_row, log, payload_object, read_input, text_field

REASON = "confidence_label_missing"
CONFIDENCE_LABEL = re.compile(r"\((verified|inferred|guess)([^)]*)?\)")


def main() -> int:
    """Emit an advisory for an unlabeled substantive Stop or SubagentStop message; always exit 0."""
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
    fields = f"hook=confidence_labels event={event} session={session_id} text_len={len(message)}"
    log(f"{fields} would_block=1 demoted=1 blocked=0 reason_code={REASON}")
    advisory = (
        f"[discipline-advisory] response >={minimum} chars made substantive claims without "
        "(verified)/(inferred)/(guess) labels. Advisory only; this lint does not block."
    )
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": advisory}}))
    append_trace_row("check_confidence_labels", "demoted", REASON, session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
