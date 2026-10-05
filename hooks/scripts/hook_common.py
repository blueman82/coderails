"""Shared stdlib primitives for root Claude hook entry points."""

from __future__ import annotations

import errno
import json
import os
import select
import sys
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Union, cast

RESOURCE_ERRNOS = frozenset({errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENOMEM})
RESOURCE_MESSAGE = (
    "Host resource exhaustion (for example too many open files) prevented this hook from running its checks. "
    "This says nothing about the action or its state: retry."
)


class HostResourceError(OSError):
    """The host could not deliver hook input; this says nothing about the guarded action."""


JsonScalar = Union[None, bool, int, float, str]
JsonValue = Union[JsonScalar, list["JsonValue"], dict[str, "JsonValue"]]


def read_payload(timeout_seconds: float = 5.0) -> dict[str, JsonValue]:
    """Read hook stdin for at most five seconds; malformed input or host exhaustion fails open (logged)."""
    try:
        return read_payload_strict(timeout_seconds)
    except HostResourceError:
        return {}


def read_payload_strict(timeout_seconds: float = 5.0) -> dict[str, JsonValue]:
    """Like read_payload, but raise HostResourceError on host exhaustion; only gates that deny should use it."""
    try:
        descriptor = sys.stdin.fileno()
        chunks = bytearray()
        deadline = time.monotonic() + timeout_seconds
        while (remaining := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([descriptor], [], [], remaining)
            if not ready:
                break
            try:
                chunk = os.read(descriptor, 65536)
            except BlockingIOError:  # EAGAIN on a nonblocking pipe is not host exhaustion
                continue
            if not chunk:
                break
            chunks.extend(chunk)
        raw = chunks.decode(errors="replace")
        decoded = cast(JsonValue, json.loads(raw)) if raw else {}
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, OSError) and error.errno in RESOURCE_ERRNOS:
            name = errno.errorcode.get(error.errno or 0, "?")
            log(f"hook=read_payload resource_exhausted errno={name} {RESOURCE_MESSAGE}")
            raise HostResourceError(error.errno, RESOURCE_MESSAGE) from error
        return {}
    return decoded if isinstance(decoded, dict) else {}


def output(event: str, **values: str) -> None:
    """Emit a hook-specific JSON payload; a deny decision is also flagged for telemetry (cause deny, not ok)."""
    if values.get("permissionDecision") == "deny":
        with suppress(ImportError):  # telemetry must never be able to break the hook
            from hooks.scripts.lib.hook_telemetry import mark_deny

            mark_deny()
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
