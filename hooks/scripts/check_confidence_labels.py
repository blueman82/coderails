#!/usr/bin/env python3
"""Require confidence labels on substantive assistant output outside active loops."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import output, read_payload
from hooks.scripts.lib.agentic_loop_path import sanitise_session_id
from hooks.scripts.lib.discipline_common import stable_text
from hooks.scripts.lib.loop_state_common import log, loop_active_incomplete
from hooks.scripts.lib.trace_row import append_row

REASON = "confidence_label_missing"


def main() -> int:
    """Enforce confidence labels with Stop-only loop and headless demotion."""
    payload = read_payload()
    event = str(payload.get("hook_event_name") or "Stop")
    if os.environ.get("CODERAILS_HEADLESS_RUN") == "1" and event == "Stop":
        log("hook=confidence_labels skipped=headless")
        return 0
    if payload.get("stop_hook_active") is True:
        return 0
    transcript = str(payload.get("transcript_path") or "")
    attempts = 1
    if event == "SubagentStop":
        text = str(payload.get("last_assistant_message") or "")
    else:
        if not transcript or not Path(transcript).is_file():
            return 0
        text, _ = stable_text(
            transcript,
            int(os.environ.get("CLAUDE_HOOK_TAIL_LINES", "200")),
            int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5")),
            float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3")),
        )
        attempts = 0
    session = str(payload.get("session_id") or "?")
    minimum = int(os.environ.get("CLAUDE_HOOK_MIN_LEN", "200"))
    matched = bool(re.search(r"\((verified|inferred|guess)", text))
    blocked = len(text) >= minimum and not matched
    fields = f"hook=confidence_labels event={event} session={session} text_len={len(text)}"
    log(f"{fields} attempts={attempts} matched={int(matched)} would_block={int(blocked)}")
    if not blocked:
        return 0
    if event == "Stop" and loop_active_incomplete(
        transcript, str(payload.get("cwd") or ""), sanitise_session_id(session)
    ):
        output(
            "Stop",
            additionalContext="[discipline-warn(loop)] response made substantive claims without "
            "(verified)/(inferred)/(guess) labels. Add them before stopping.",
        )
        log(f"{fields} would_block=1 warned=1 blocked=0 reason_code={REASON}")
        append_row("check_confidence_labels", "warned", REASON, session)
        return 0
    log(f"{fields} blocked=1 reason_code={REASON}")
    append_row("check_confidence_labels", "blocked", REASON, session)
    print(
        f"[discipline-block] response >={minimum} chars with no confidence label. Rule (CLAUDE.md): "
        "tag each substantive claim (verified)/(inferred)/(guess) — e.g. "
        '"the cache matches the repo (verified — diffed both trees)". '
        "Add labels to the claims you made, then stop again.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
