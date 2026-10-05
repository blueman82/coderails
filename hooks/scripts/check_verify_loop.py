#!/usr/bin/env python3
"""Advise (never block) on silently deferred verification and omitted verification sections."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import output, read_payload
from hooks.scripts.lib.discipline_common import file_count, stable_text
from hooks.scripts.lib.loop_state_common import log
from hooks.scripts.lib.trace_row import append_row

REASON = "verify_loop_missing"


def verification_items(text: str) -> tuple[bool, list[str], int]:
    """Extract verification bullets and count nonempty bullets without a leading waiver."""
    header, active = False, False
    bullets: list[str] = []
    for line in text.splitlines():
        if re.match(r"^## *(Did Not Verify|Not Verified)", line):
            header, active = True, True
        elif line.startswith("## "):
            active = False
        elif active and line.startswith("- "):
            bullets.append(line)
    untagged = sum(
        bool(re.match(r"^- *\S", line)) and not re.match(r"^- *\(unverifiable:", line, re.I) for line in bullets
    )
    return header, bullets, untagged


def main() -> int:
    """Police the current turn or a worker's direct final message."""
    payload = read_payload()
    event = str(payload.get("hook_event_name") or "Stop")
    if os.environ.get("CODERAILS_HEADLESS_RUN") == "1" and event == "Stop":
        log("hook=verify_loop skipped=headless")
        return 0
    transcript = str(payload.get("transcript_path") or "")
    count, attempts = 0, 0
    if event == "SubagentStop":
        text = str(payload.get("last_assistant_message") or "")
    else:
        if not transcript or not Path(transcript).is_file():
            return 0
        count = file_count(transcript)
        text, _ = stable_text(
            transcript,
            int(os.environ.get("CLAUDE_HOOK_TAIL_LINES", "200")),
            int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5")),
            float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3")),
        )
    if payload.get("stop_hook_active") is True:
        return 0
    session = str(payload.get("session_id") or "?")
    fields = f"hook=verify_loop event={event} session={session} text_len={len(text)} attempts={attempts} files={count}"
    if not text:
        log(f"{fields} skipped=empty_text blocked=0")
        return 0
    header, bullets, untagged = verification_items(text)
    message = ""
    presence = not header and count >= 3
    if presence:
        message = (
            f'[discipline-advisory] session modified {count} files but the response has no "## Did Not Verify" '
            "section. Rule (CLAUDE.md): after any response that edits files, end with a ## Did Not Verify "
            "section — resolve each item or tag it (unverifiable: <reason>). Consider adding it; advisory only."
        )
    elif untagged:
        message = (
            "[discipline-advisory] Your '## Did Not Verify' section has untagged items — anything not\n"
            "explicitly marked uncheckable is treated as something you could have resolved:\n"
            + "\n".join(bullets)
            + "\n"
            "Resolve each before stopping: read the file, run the check (Read/Grep/Bash), or delete the bullet.\n"
            "If an item GENUINELY cannot be checked from source (a REPL-only action, external-system\n"
            "behaviour, prod-only observation, or user intent), keep it but tag its leading clause:\n"
            "  - (unverifiable: <reason>) <the item>\n"
            "That tag marks an item as genuinely uncheckable; every untagged bullet is flagged, file-naming or not.\n"
            "Advisory only; this lint does not block."
        )
    fields += f" dnv_items={len(bullets)} resolvable_dnv_items={untagged}"
    if presence:
        fields += " presence_block=1"
    if not message:
        log(f"{fields} blocked=0")
        return 0
    output(event, additionalContext=message)
    log(f"{fields} would_block=1 demoted=1 blocked=0 reason_code={REASON}")
    append_row("check_verify_loop", "demoted", REASON, session)
    return 0


if __name__ == "__main__":
    try:
        from hooks.scripts.lib.hook_telemetry import run
    except ImportError:  # telemetry must never be able to break the hook
        raise SystemExit(main()) from None
    raise SystemExit(run("check_verify_loop", main))
