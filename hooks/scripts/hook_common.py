"""Shared stdlib primitives for root Claude hook entry points."""

from __future__ import annotations

import json
import os
import select
import sys
from datetime import datetime
from pathlib import Path
from typing import Union, cast

JsonScalar = Union[None, bool, int, float, str]
JsonValue = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]


def read_payload() -> dict[str, JsonValue]:
    """Read hook stdin for at most five seconds; malformed input fails open."""
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 5)
        raw = sys.stdin.read() if ready else ""
        decoded = cast(JsonValue, json.loads(raw)) if raw else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def output(event: str, **values: str) -> None:
    """Emit a hook-specific JSON payload."""
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **values}}))


def deny(reason: str) -> None:
    """Emit a PreToolUse denial with its reason."""
    output("PreToolUse", permissionDecision="deny", permissionDecisionReason=reason)


def log(message: str) -> None:
    """Append a best-effort timestamped discipline-log message."""
    path = Path(os.environ.get("CLAUDE_DISCIPLINE_LOG", Path.home() / ".claude" / "discipline.log"))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().astimezone().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass
