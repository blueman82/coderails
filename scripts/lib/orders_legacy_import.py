"""Archive one parsed legacy byte snapshot before publishing its ledger rows."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

from scripts.lib import orders_ledger as ol
from scripts.lib import orders_lifecycle as lifecycle


def _backup_path(repo_dir: Path, n: int) -> Path:
    return repo_dir / ("standing-orders.legacy.md" if n == 1 else f"standing-orders.legacy.{n}.md")


def _same_archive(path: Path, raw: bytes) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and path.read_bytes() == raw
    except OSError:
        return False


def _archive(repo_dir: Path, raw: bytes, retry: bool) -> Path:
    """Publish a private copy under an unused name; keep every published archive."""
    if retry:
        for n in range(1, 1000):
            candidate = _backup_path(repo_dir, n)
            if _same_archive(candidate, raw):
                return candidate
    fd, name = tempfile.mkstemp(prefix=".standing-orders-legacy-", dir=repo_dir)
    staged = Path(name)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        for n in range(1, 1000):
            candidate = _backup_path(repo_dir, n)
            try:
                os.link(staged, candidate)
            except FileExistsError:
                continue
            return candidate
        raise ValueError("legacy_parse_error")
    finally:
        staged.unlink(missing_ok=True)


def apply(
    repo_dir: Path,
    raw: bytes,
    text: str,
    parsed: list[dict[str, Any]],
    ledger: ol.Ledger,
) -> dict[str, Any]:
    """Archive the parsed bytes, then publish rows under the caller's orders lock."""
    source_hash = hashlib.sha256(raw).hexdigest()
    parsed = [{**row, "legacy_source_sha256": source_hash} for row in parsed]
    for row in parsed:
        lifecycle.check_staged_identity(repo_dir, ledger, row)
    have = {order["id"]: order for order in ledger["orders"]}
    shared = [row for row in parsed if row["id"] in have]
    if shared:
        timestamps = {have[row["id"]]["created"] for row in shared}
        expected = ol.parse_legacy(text, have[shared[0]["id"]]["created"])
        expected = [{**row, "legacy_source_sha256": source_hash} for row in expected]
        if (
            len(shared) != len(parsed)
            or len(timestamps) != 1
            or any(
                {
                    key: value
                    for key, value in have[row["id"]].items()
                    if key not in ("seq", "prev_sha256", "row_sha256")
                }
                != row
                for row in expected
            )
        ):
            raise ValueError("legacy_parse_error")

    archive = _archive(repo_dir, raw, bool(shared))
    if not shared:
        new = {**ledger, "orders": [*ledger["orders"], *parsed]}
        sealed = ol.seal(new)
        try:
            ol.save(repo_dir / "orders.json", sealed)
        except (OSError, ValueError):
            try:
                committed = ol.open_ledger(repo_dir) == sealed
            except (OSError, ValueError, ol.ChainError):
                committed = False
            if not committed:
                raise ValueError("order_state_error") from None
    return {
        "imported": 0 if shared else len(parsed),
        "skipped": len(shared),
        "archived_to": str(archive),
        "source_retained": True,
    }
