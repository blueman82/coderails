#!/usr/bin/env python3
"""Advise (never block) when substantive assistant output carries no confidence labels."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import output, read_payload
from hooks.scripts.lib.discipline_common import stable_text
from hooks.scripts.lib.loop_state_common import log
from hooks.scripts.lib.trace_row import append_row

REASON = "confidence_label_missing"


def main() -> int:
    """Emit an advisory for unlabeled substantive output; Stop skips headless runs."""
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
    output(
        event,
        additionalContext=f"[discipline-advisory] response >={minimum} chars made substantive claims without "
        '(verified)/(inferred)/(guess) labels (rule: CLAUDE.md), e.g. "the cache matches the repo (verified: '
        'diffed both trees)". Advisory only; this lint does not block.',
    )
    log(f"{fields} demoted=1 blocked=0 reason_code={REASON}")
    append_row("check_confidence_labels", "demoted", REASON, session)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
