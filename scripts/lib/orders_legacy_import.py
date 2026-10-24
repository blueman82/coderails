"""Capture a hand-written order source before publishing its ledger rows."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from scripts.lib import orders_ledger as ol
from scripts.lib import orders_lifecycle as lifecycle


def _restore_unclaimed_source(src: Path, backup: Path) -> None:
    """Restore the captured name without replacing an editor's new source file."""
    if src.exists() or src.is_symlink() or backup.is_symlink():
        return
    try:
        os.link(backup, src)
    except OSError:
        return
    with suppress(OSError):
        backup.unlink()  # a failed unlink leaves both names preserving the captured bytes


def _backup_path(repo_dir: Path) -> Path:
    """Select the first free legacy backup name under the held orders lock."""
    for n in range(1, 1000):
        dest = repo_dir / ("standing-orders.legacy.md" if n == 1 else f"standing-orders.legacy.{n}.md")
        if not dest.exists() and not dest.is_symlink():
            return dest
    raise ValueError("legacy_parse_error")


def apply(
    repo_dir: Path,
    src: Path,
    raw: bytes,
    text: str,
    parsed: list[dict[str, Any]],
    ledger: ol.Ledger,
) -> dict[str, Any]:
    """Archive the exact parsed source, then publish its rows while the caller holds the one lock."""
    new = {**ledger, "orders": list(ledger["orders"])}
    for row in parsed:
        lifecycle.check_staged_identity(repo_dir, ledger, row)
    have = {order["id"]: order for order in new["orders"]}
    shared = [row for row in parsed if row["id"] in have]
    if shared:
        timestamps = {have[row["id"]]["created"] for row in shared}
        expected = ol.parse_legacy(text, have[shared[0]["id"]]["created"])
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

    dest = _backup_path(repo_dir)
    os.replace(src, dest)
    try:
        if dest.is_symlink() or not dest.is_file() or dest.read_bytes() != raw:
            raise ValueError("legacy_parse_error")
    except (OSError, ValueError):
        _restore_unclaimed_source(src, dest)
        raise ValueError("legacy_parse_error") from None

    if not shared:
        new["orders"] += parsed
        sealed = ol.seal(new)
        try:
            ol.save(repo_dir / "orders.json", sealed)
        except (OSError, ValueError):
            try:
                committed = ol.open_ledger(repo_dir) == sealed
            except (OSError, ValueError, ol.ChainError):
                committed = False
            if not committed:
                _restore_unclaimed_source(src, dest)
                raise
    return {"imported": 0 if shared else len(parsed), "skipped": len(shared), "moved_to": str(dest)}
