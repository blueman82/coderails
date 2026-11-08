"""Pure canonical decision-chain hashes; no provider, memory, locking or I/O dependencies."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

GENESIS, HASH_EXCLUDED = "0" * 64, ("row_sha256", "muninn")


def row_digest(row: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the row minus `muninn` and `row_sha256`."""
    body = {k: v for k, v in row.items() if k not in HASH_EXCLUDED}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _rows(state: dict[str, Any]) -> list[Any]:
    value: Any = state.get("decisions_absorbed", [])
    if not isinstance(value, list):
        raise ValueError("invalid_chain")
    rows: list[Any] = list(value)  # pyright: ignore[reportUnknownArgumentType]
    return rows


def _as_row(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """A decision row as a dict; anything else (a hand-written string, null) is an empty row."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def verify_chain(rows: list[Any], chain_start: int | None = None) -> list[dict[str, Any]]:
    """Return offenders `{seq, reason}`; empty means clean. Rows before the first hashed row are legacy and ignored.

    Pass the state's `chain_started_seq` as `chain_start` so unhashed rows at or after it are offenders even when every
    hash was stripped; without it an all-unhashed list verifies clean (the marker lives in the same file, so a
    same-user agent that also deletes it is the documented boundary).
    """
    bad: list[dict[str, Any]] = []
    hashed = False
    prev = GENESIS
    for index, item in enumerate(rows, start=1):
        row = _as_row(item)
        if not row.get("row_sha256"):
            if hashed or (chain_start is not None and index >= chain_start):
                bad.append({"seq": index, "reason": "unhashed_row"})
            prev = GENESIS
            continue
        hashed = True
        if row.get("seq") != index:
            bad.append({"seq": row.get("seq", index), "reason": "bad_seq"})
        if row.get("prev_sha256") != prev:
            bad.append({"seq": row.get("seq", index), "reason": "bad_prev"})
        if row_digest(row) != row["row_sha256"]:
            bad.append({"seq": row.get("seq", index), "reason": "bad_hash"})
        prev = str(row["row_sha256"])
    return bad


def ensure_chain(state: dict[str, Any]) -> None:
    """Refuse a damaged decision chain before another local or external write."""
    marker = state.get("chain_started_seq")
    if marker is not None and (type(marker) is not int or marker < 1):
        raise ValueError("invalid_chain")
    if verify_chain(_rows(state), marker):
        raise ValueError("invalid_chain")


as_row = _as_row
rows = _rows
