"""Fail-closed validation of the pinned Muninn current-record and citation response."""

from __future__ import annotations

import datetime
import math
import re
import time
from typing import Any, cast

from scripts.lib import memory_cite

TYPES = ("fact", "decision", "preference", "constraint", "lesson")
TAG = re.compile(r"[a-z0-9_-]{1,32}")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
KID = re.compile(r"K\d+")


def expired(valid_until: object) -> bool:
    """Expiry is inclusive; retain timestamp precision and exclude malformed or naive values."""
    if valid_until in (None, ""):
        return False
    try:
        if type(valid_until) in (int, float):
            numeric = float(cast("int | float", valid_until))
            return not math.isfinite(numeric) or numeric <= time.time()
        if isinstance(valid_until, str) and DATE.fullmatch(valid_until):
            return datetime.date.fromisoformat(valid_until) <= datetime.date.today()
        instant = datetime.datetime.fromisoformat(str(valid_until).replace("Z", "+00:00"))
        return instant.tzinfo is None or instant.timestamp() <= time.time()
    except (ValueError, OverflowError):
        return True


def anchor(entry: dict[str, Any]) -> dict[str, str] | None:
    """Only explicitly current, typed, normal records with a live verified user-prompt anchor may be served."""
    strings = ("id", "kind", "text", "scope")
    if any(not isinstance(entry.get(k), str) or not entry[k].strip() for k in strings):
        return None
    if not KID.fullmatch(entry["id"]) or entry["kind"] not in TYPES or entry.get("status") != "current":
        return None
    raw_tags, raw_cites = entry.get("tags"), entry.get("cites")
    tags = cast("list[Any]", raw_tags)
    if not isinstance(raw_tags, list):
        return None
    if any(not isinstance(t, str) or not TAG.fullmatch(t) for t in tags):
        return None
    if entry.get("sensitivity") != "normal" or entry.get("expired") is not False or expired(entry.get("valid_until")):
        return None
    values = cast("list[Any]", raw_cites)
    if not isinstance(raw_cites, list) or not raw_cites:
        return None
    if any(not isinstance(c, dict) for c in values):
        return None
    cites = [cast("dict[str, Any]", c) for c in values]
    for cite in cites:
        if cite.get("state") != "live" or cite.get("verify") != "ok":
            return None
    return next(
        (
            cast("dict[str, str]", c)
            for c in cites
            if (c.get("role"), c.get("kind")) == ("user", "prompt")
            and isinstance(c.get("ref"), str)
            and memory_cite.REF.fullmatch(c["ref"])
            and isinstance(c.get("quote"), str)
            and c["quote"].strip()
        ),
        None,
    )
