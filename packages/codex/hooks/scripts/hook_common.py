"""Small shared primitives for native Codex Python hooks."""

from __future__ import annotations

import json
import os
import select
import sys
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import cast


def read_input(timeout_seconds: float = 5.0) -> str:
    """Read available stdin bytes for at most the established hook timeout."""
    descriptor = sys.stdin.fileno()
    chunks = bytearray()
    deadline = time.monotonic() + timeout_seconds
    with suppress(OSError):
        os.set_blocking(descriptor, False)
    while (remaining := deadline - time.monotonic()) > 0:
        readable, _, _ = select.select([descriptor], [], [], remaining)
        if not readable:
            break
        try:
            chunk = os.read(descriptor, 65536)
        except BlockingIOError:
            continue
        if not chunk:
            break
        chunks.extend(chunk)
    return chunks.decode(errors="replace")


def payload_object(raw_payload: str) -> dict[str, object]:
    """Decode a hook payload, treating malformed input as an empty mapping."""
    try:
        decoded: object = json.loads(raw_payload)
    except json.JSONDecodeError:
        return {}
    return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}


def text_field(payload: dict[str, object], name: str, default: str = "") -> str:
    """Return a string field, or the caller's established fallback."""
    value = payload.get(name)
    return value if isinstance(value, str) else default


def log(message: str) -> None:
    """Append a best-effort timestamped discipline record."""
    data_dir = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails" / "codex")))
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        log_file = Path(os.environ.get("CODERAILS_DISCIPLINE_LOG", data_dir / "discipline.log"))
        with log_file.open("a", encoding="utf-8") as output:
            output.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")
    except OSError:
        return


def continue_turn(reason: str) -> None:
    """Emit the established Stop-hook block response."""
    print(json.dumps({"decision": "block", "reason": reason}))


def deny(reason: str) -> None:
    """Emit the native PreToolUse denial envelope."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )


def session_dir(session_id: str) -> Path | None:
    """Return the session-only data directory, or none for an empty identity."""
    safe_session = session_id.replace("/", "_").replace("..", "")
    if not safe_session:
        return None
    data_dir = Path(os.environ.get("PLUGIN_DATA", str(Path.home() / ".coderails" / "codex")))
    return data_dir / "sessions" / safe_session


def stamp(path: Path) -> bool:
    """Write the established local timestamp, returning false on any I/O failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{datetime.now().astimezone().isoformat(timespec='seconds')}\n", encoding="utf-8")
    except OSError:
        return False
    return True
