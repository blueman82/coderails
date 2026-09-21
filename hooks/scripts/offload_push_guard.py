#!/usr/bin/env python3
"""Warn once when a final message offloads a main-branch push to the user."""

from __future__ import annotations

import os
import re
from json import JSONDecodeError, loads
from pathlib import Path
from typing import cast

from hook_common import JsonValue, log, output, read_payload

PUSH = re.compile(r"git(?: +-C +[^ ]+)? +push\b.*\b(?:origin +)?(?:main|master)\b", re.I)
OFFLOAD = re.compile(
    r"(?:^|[^\w])! +git|your own shell|run (?:it|this) yourself|from your shell|you run|"
    r"needs your shell|un-?gated shell",
    re.I,
)


def text_from(path: str) -> str:
    """Extract assistant text from a transcript, failing open on malformed input."""
    try:
        texts: list[str] = []
        for line in Path(path).read_text().splitlines():
            block = cast(JsonValue, loads(line))
            if not isinstance(block, dict) or block.get("type") != "assistant":
                continue
            message = block.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list) or not content:
                continue
            final = content[-1]
            if isinstance(final, dict):
                value = final.get("text")
                if isinstance(value, str):
                    texts.append(value)
        return "\n".join(texts)
    except (OSError, JSONDecodeError):
        return ""


def main() -> int:
    """Emit a once-per-session warning for an offloaded main push."""
    payload = read_payload()
    event_value = payload.get("hook_event_name", "Stop")
    event = event_value if isinstance(event_value, str) else "Stop"
    sid_value = payload.get("session_id", "?")
    sid = str(sid_value).replace("/", "_").replace("..", "")
    message = payload.get("last_assistant_message", "")
    transcript = payload.get("transcript_path", "")
    text = (
        message
        if event == "SubagentStop" and isinstance(message, str)
        else text_from(transcript if isinstance(transcript, str) else "")
    )
    if not PUSH.search(text) or not OFFLOAD.search(text):
        return 0
    log_path = Path(os.environ.get("CLAUDE_DISCIPLINE_LOG", str(Path.home() / ".claude/discipline.log")))
    try:
        if f"session={sid} nudged=1" in log_path.read_text(encoding="utf-8"):
            return 0
    except OSError:
        pass
    log(f"hook=offload_push_guard session={sid} nudged=1")
    output(
        "Stop",
        additionalContext=(
            "[offload-guard] Your final message asks the user to run a git push that this session can clear "
            "itself. Run review-pr here, then push yourself."
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
