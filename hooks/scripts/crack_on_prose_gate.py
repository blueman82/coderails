#!/usr/bin/env python3
"""Block prose questions while the session's crack-on envelope is active."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

from hook_common import JsonValue, log, read_payload

MODAL = re.compile(r"(^|[^a-z0-9])(should|shall|could|can|may|must|do|would) (i|we) [^?]*\?\s*$", re.IGNORECASE)
ASK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"do you (want|need|prefer)",
        r"want me to [^?]*\?",
        r"would you (like|prefer|rather)",
        r"let me know (if|which|what|whether|when|how|your)",
        r"tell me (which|what|whether|if)",
        r"which (do|would|should) you",
        r"(awaiting|waiting (on|for)) your",
        r"please (confirm|advise|clarify|choose|pick|decide)",
        r"(give|need|await|wait for) (me )?the (go-ahead|green light)",
        r"say the word",
        r"how would you like",
        r"what would you (like|prefer)",
        r"if you('d)? (want|like|prefer), (i|we) can",
        r"(is|would) that (be )?(ok|okay|alright|acceptable)",
        r"your (call|choice|preference)[\W\s]*$",
    )
)
TRAILING_DECORATION = re.compile(r"[\]\")'*_:\s]*$")


def text(payload: dict[str, JsonValue], name: str) -> str:
    """Return a string payload field or the established empty default."""
    value = payload.get(name)
    return value if isinstance(value, str) else ""


def flag_path(session_id: str) -> Path | None:
    """Return the session-only flag path without graph-path existence probing."""
    session_id = session_id.replace("/", "_").replace("..", "")
    if not session_id:
        return None
    base = Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", Path.home() / ".coderails" / "agentic-loop"))
    return base / session_id / "crack_on_active"


def stable_text(transcript: Path, tail_lines: int, max_attempts: int, sleep_seconds: float) -> str:
    """Return the last assistant text after its transcript flush length stabilises."""
    previous_length = -1
    result = ""
    for attempt in range(max_attempts):
        try:
            lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()[-tail_lines:]
        except OSError:
            return ""
        messages: list[str] = []
        for line in lines:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            item = cast(JsonValue, item)
            if not isinstance(item, dict) or item.get("type") != "assistant":
                continue
            message = item.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content:
                messages.append(content)
            elif isinstance(content, list):
                blocks: list[str] = []
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue
                    value = block.get("text")
                    if isinstance(value, str):
                        blocks.append(value)
                if blocks:
                    messages.append(" ".join(blocks))
        result = messages[-1] if messages else ""
        if len(result) == previous_length and result:
            return result
        previous_length = len(result)
        if attempt + 1 < max_attempts:
            time.sleep(sleep_seconds)
    return result


def prose(text_value: str) -> str:
    """Drop fenced, inline-code, and quoted material before matching prose."""
    fenced = False
    lines: list[str] = []
    for line in text_value.splitlines():
        if re.match(r"^\s*```", line):
            fenced = not fenced
        elif not fenced and not re.match(r"^\s*>", line):
            lines.append(re.sub(r"`[^`]*`", "", line))
    return "\n".join(lines)


def match_question(text_value: str) -> tuple[str, str] | None:
    """Return the deterministic match level and source snippet, if any."""
    stripped = prose(text_value)
    body = re.split(r"^## *(?:Did Not Verify|Not Verified)\s*$", stripped, maxsplit=1, flags=re.MULTILINE)[0]
    body_lines = [line for line in body.splitlines() if line.strip()]
    whole_lines = [line for line in stripped.splitlines() if line.strip()]
    for level, line in (
        ("verification_level1_body_last", body_lines[-1] if body_lines else ""),
        ("verification_level1_whole_last", whole_lines[-1] if whole_lines else ""),
    ):
        if TRAILING_DECORATION.sub("", line).endswith("?"):
            return level, line
    for line in body_lines[-3:]:
        if MODAL.search(line):
            return "verification_level1b_modal", line
    for pattern in ASK_PATTERNS:
        if match := pattern.search(stripped):
            return "verification_level2", match.group(0)
    return None


def counter(flag: Path, active: bool) -> tuple[Path, int]:
    """Reset at first Stop attempt or read the continuation attempt's count."""
    path = flag.parent / "prose_question_blocks"
    if not active:
        with suppress(OSError):
            path.unlink(missing_ok=True)
        return path, 0
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return path, int(raw) if raw.isdigit() else 0
    except OSError:
        return path, 0


def main() -> int:
    """Block a matching final message, retaining the per-turn release valve."""
    payload = read_payload()
    if text(payload, "hook_event_name") != "Stop":
        return 0
    session_id = text(payload, "session_id")
    if not session_id:
        return 0
    if os.environ.get("CODERAILS_HEADLESS_RUN") == "1":
        log("hook=crack_on_prose_gate skipped=headless")
        return 0
    flag = flag_path(session_id)
    if flag is None or not flag.is_file():
        return 0
    transcript_name = text(payload, "transcript_path")
    if not transcript_name or not Path(transcript_name).is_file():
        return 0
    try:
        tail_lines = int(os.environ.get("CLAUDE_HOOK_TAIL_LINES", "300"))
        max_attempts = int(os.environ.get("CLAUDE_HOOK_MAX_ATTEMPTS", "5"))
        sleep_seconds = float(os.environ.get("CLAUDE_HOOK_SLEEP_S", "0.3"))
        max_blocks = int(os.environ.get("CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS", "3"))
    except ValueError:
        return 0
    active = payload.get("stop_hook_active") is True or text(payload, "stop_hook_active") == "true"
    count_file, count = counter(flag, active)
    final_text = stable_text(Path(transcript_name), tail_lines, max_attempts, sleep_seconds)
    if not final_text:
        log(f"hook=crack_on_prose_gate event=Stop session={session_id} skipped=empty_text blocked=0")
        return 0
    match = match_question(final_text)
    if match is None:
        log(f"hook=crack_on_prose_gate event=Stop session={session_id} text_len={len(final_text)} matched=0 blocked=0")
        return 0
    level, snippet = match
    if count >= max_blocks:
        log(
            f"hook=crack_on_prose_gate event=Stop session={session_id} text_len={len(final_text)} "
            f"matched=1 verification_level={level} count={count} capped=1 blocked=0"
        )
        return 0
    try:
        count_file.write_text(str(count + 1), encoding="utf-8")
    except OSError:
        log(
            f"hook=crack_on_prose_gate event=Stop session={session_id} matched=1 "
            f"verification_level={level} blocked=0 err=count_write_failed"
        )
        return 0
    log(
        f"hook=crack_on_prose_gate event=Stop session={session_id} text_len={len(final_text)} "
        f"matched=1 verification_level={level} count={count + 1} blocked=1"
    )
    print(
        f"[crack-on-block] A crack-on envelope is active in this session and your final message hands a "
        f'question back to the user (matched: "{snippet}"). Asking the human is suppressed in BOTH forms '
        "— the AskUserQuestion tool and prose. Make the call yourself inside the envelope scope and keep "
        "working, or end with a declarative report / LOOP-STOP declaration stating what you did, what you "
        "decided, and what remains. Do not end the turn with a question, and do not rephrase this one.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
