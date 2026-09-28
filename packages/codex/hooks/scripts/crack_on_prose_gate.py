#!/usr/bin/env python3
"""Continue an active crack-on turn when its final prose hands back a question."""
from __future__ import annotations

import os
import re
from pathlib import Path

from hook_common import continue_turn, log, payload_object, read_input, session_dir, text_field


def asks_question(message: str) -> bool:
    """Match the established unfenced, unquoted final-prose question forms."""
    lines: list[str] = []
    fenced = False
    for line in message.splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced or re.match(r"\s*>", line):
            continue
        if line.startswith("## Did Not Verify"):
            break
        lines.append(re.sub(r"`[^`]*`", "", line))
    nonempty = [line for line in lines if line.strip()]
    if not nonempty:
        return False
    return bool(
        re.search(r"""\?[\s"')\]*_]*$""", nonempty[-1])
        or re.search(r"(?im)^\s*(should|shall|can|could|may|might|would)\s+(I|we)\b.*\?", "\n".join(lines[-3:]))
        or re.search(
            r"(?i)\b(do you want|would you prefer|which would you|let me know|please choose|awaiting your|"
            r"need your decision|can you|could you|would you)\b",
            "\n".join(lines),
        )
    )


def block_count(path: Path, active: object) -> int:
    """Read the bounded counter only during a repeated Stop-hook turn."""
    if active is not True:
        return 0
    try:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        return int(first) if re.fullmatch(r"[0-9]+", first) else 0
    except (OSError, IndexError, ValueError):
        return 0


def main() -> None:
    """Apply the session flag and fail-open infrastructure/counter limits."""
    payload = payload_object(read_input())
    session = text_field(payload, "session_id")
    directory = session_dir(session)
    if directory is None or not (directory / "crack_on_active").is_file():
        print("{}")
        return
    if not asks_question(text_field(payload, "last_assistant_message")):
        print("{}")
        return
    counter = directory / "prose_question_blocks"
    count = block_count(counter, payload.get("stop_hook_active"))
    try:
        maximum = int(os.environ.get("CODERAILS_CRACK_ON_PROSE_MAX_BLOCKS", "3"))
        if count >= maximum:
            log(f"hook=crack_on_prose_gate session={session} capped=1 count={count}")
            print("{}")
            return
        directory.mkdir(parents=True, exist_ok=True)
        counter.write_text(f"{count + 1}\n", encoding="utf-8")
    except (OSError, ValueError):
        print("{}")
        return
    log(f"hook=crack_on_prose_gate session={session} blocked=1 count={count + 1}")
    continue_turn(
        "Crack-on is active and the final message ends by asking the user. "
        "Make the decision yourself within scope and keep working, or finish with a declarative report."
    )


if __name__ == "__main__":
    main()
