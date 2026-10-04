#!/usr/bin/env python3
"""Pure authority-object validation plus exact-id, atomic storage. Additive: no gate consults it yet."""

from __future__ import annotations

import json
import os
import sys
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.trace_row import append_row

FIELDS = (
    "authority_id",
    "loop_id",
    "session_id",
    "scope",
    "denied",
    "max_prs",
    "expires_at",
    "revocable",
    "approval_required_for",
)
MERGE = "merge"


def safe_session(session_id: object) -> bool:
    """Accept only a nonempty id that is path-local as written; never sanitise, so ids cannot collide."""
    return (
        isinstance(session_id, str)
        and bool(session_id)
        and session_id != "."
        and "/" not in session_id
        and ".." not in session_id
        and "\0" not in session_id
    )


def authority_path(session_id: str, base: Path | None = None) -> Path | None:
    """Return <loop dir>/<session_id>/authority.json, or None for an unsafe id."""
    if not safe_session(session_id):
        return None
    root = base or Path(os.environ.get("CLAUDE_AGENTIC_LOOP_DIR", str(Path.home() / ".coderails/agentic-loop")))
    return root / session_id / "authority.json"


def parse_time(value: object) -> datetime | None:
    """Parse a timezone-aware ISO-8601 time, or None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def string_list(value: object) -> bool:
    """True for a list of nonempty strings."""
    items = cast("list[object]", value) if isinstance(value, list) else None
    return items is not None and all(isinstance(item, str) and item for item in items)


def validate(obj: object, now: datetime) -> list[str]:
    """Return every problem with an authority object; an empty list means valid and unexpired."""
    if not isinstance(obj, dict):
        return ["not_an_object"]
    data = cast("dict[str, Any]", obj)
    errors = [f"missing:{name}" for name in FIELDS if name not in data]
    errors += [f"unknown:{name}" for name in data if name not in FIELDS]
    if errors:
        return errors
    if not isinstance(data["authority_id"], str) or not data["authority_id"]:
        errors.append("authority_id")
    if data["loop_id"] is not None and (not isinstance(data["loop_id"], str) or not data["loop_id"]):
        errors.append("loop_id")
    if not safe_session(data["session_id"]):
        errors.append("session_id")
    for name in ("scope", "denied", "approval_required_for"):
        if not string_list(data[name]):
            errors.append(name)
    max_prs = data["max_prs"]
    if isinstance(max_prs, bool) or not isinstance(max_prs, int) or max_prs < 0:
        errors.append("max_prs")
    if not isinstance(data["revocable"], bool):
        errors.append("revocable")
    expires = parse_time(data["expires_at"])
    if expires is None:
        errors.append("expires_at")
    elif expires <= now:
        errors.append("expired")
    if errors:
        return errors
    if MERGE not in data["approval_required_for"]:
        errors.append("approval_required_for_must_include_merge")
    if set(data["scope"]) & set(data["denied"]):
        errors.append("scope_denied_overlap")
    return errors


def write_authority(path: Path, obj: dict[str, Any]) -> bool:
    """Write atomically (tmp + os.replace): a crash leaves the old file or none. False on any OSError."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        with suppress(OSError):
            tmp.unlink()
        return False
    return True


def read_authority(session_id: str, base: Path | None = None, now: datetime | None = None) -> dict[str, Any] | None:
    """Return this exact session's valid, unexpired authority object, else None (nothing is granted).

    A file whose embedded session_id differs from the requested id is refused and traced as foreign.
    """
    path = authority_path(session_id, base)
    if path is None:
        return None
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    data = cast("dict[str, Any]", raw)
    if data.get("session_id") != session_id:
        append_row("authority", "refused", "authority_refused_foreign", session_id, base=base)
        return None
    return None if validate(data, now or datetime.now(timezone.utc)) else data
