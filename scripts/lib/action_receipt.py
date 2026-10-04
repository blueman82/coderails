#!/usr/bin/env python3
"""Action receipts: approval bound to one exact action. Pure verify(), atomic single-use consume, no daemon.

A receipt proves a same-user principal minted an approval for this exact command text/cwd/branch (and SHA when
bound). It does not prove the minter was a human: any agent with the same filesystem access can mint one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from scripts.lib.authority_object import authority_path, parse_time, safe_session

FIELDS = (
    "receipt_id",
    "authority_id",
    "session_id",
    "loop_id",
    "action",
    "exact_payload_hash",
    "artifact_sha",
    "scope",
    "issued_at",
    "expires_at",
    "single_use",
    "revoked",
)
REASONS = (
    "ok",
    "hash_mismatch",
    "sha_mismatch",
    "expired",
    "revoked",
    "consumed",
    "foreign_session",
    "foreign_loop",
    "malformed",
    "no_session",
    "kind_mismatch",
    "no_receipt",
)


def canonical_hash(argv: list[str], cwd: str, branch: str) -> str:
    """sha256 over the canonical JSON of argv, cwd and branch (a bare `git push` needs cwd+branch to be exact)."""
    blob = json.dumps({"argv": argv, "cwd": cwd, "branch": branch}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def proposed_action(kind: str, segment: str, cwd: str, branch: str, artifact_sha: str | None = None) -> dict[str, Any]:
    """The action as the hook sees it: shlex-normalised command text (unparseable text is kept whole)."""
    try:
        argv = shlex.split(segment)
    except ValueError:
        argv = [segment.strip()]
    return {"action": kind, "exact_payload_hash": canonical_hash(argv, cwd, branch), "artifact_sha": artifact_sha}


def receipt_path(session_id: str, receipt_id: str, base: Path | None = None) -> Path | None:
    """Return <session dir>/receipts/<receipt_id>.json, or None for a path-unsafe id (never sanitised)."""
    auth = authority_path(session_id, base)
    if auth is None or not safe_session(receipt_id):
        return None
    return auth.parent / "receipts" / f"{receipt_id}.json"


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _shape_ok(data: dict[str, Any]) -> bool:
    """Closed field set with the right types; anything else is malformed."""
    if set(data) != set(FIELDS):
        return False
    optional = all(data[name] is None or _nonempty(data[name]) for name in ("authority_id", "loop_id", "artifact_sha"))
    required = all(_nonempty(data[name]) for name in ("receipt_id", "session_id", "action", "exact_payload_hash"))
    flags = isinstance(data["single_use"], bool) and isinstance(data["revoked"], bool)
    times = parse_time(data["expires_at"]) is not None and parse_time(data["issued_at"]) is not None
    return optional and required and flags and times and isinstance(data["scope"], str)


def verify(
    rec: object, proposed: dict[str, Any], now: datetime, session_id: str, loop_id: str | None, consumed: bool = False
) -> tuple[bool, str]:
    """Pure check of one receipt against one proposed action; returns (ok, stable reason code)."""
    if not isinstance(rec, dict) or not _shape_ok(cast("dict[str, Any]", rec)):
        return False, "malformed"
    data = cast("dict[str, Any]", rec)
    if data["revoked"]:
        return False, "revoked"
    expires = parse_time(data["expires_at"])
    if expires is None or expires <= now:
        return False, "expired"
    if data["session_id"] != session_id:
        return False, "foreign_session"
    if data["loop_id"] is not None and data["loop_id"] != loop_id:
        return False, "foreign_loop"
    if consumed:
        return False, "consumed"
    if data["action"] != proposed.get("action"):
        return False, "kind_mismatch"
    if data["exact_payload_hash"] != proposed.get("exact_payload_hash"):
        return False, "hash_mismatch"
    if data["artifact_sha"] is not None and data["artifact_sha"] != proposed.get("artifact_sha"):
        return False, "sha_mismatch"
    return True, "ok"


def write_receipt(path: Path, obj: dict[str, Any]) -> bool:
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


def read_receipt(path: Path) -> dict[str, Any] | None:
    """Return the parsed receipt object, or None when missing, torn or not an object."""
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cast("dict[str, Any]", raw) if isinstance(raw, dict) else None


def _claim(path: Path, suffix: str) -> bool:
    """Create <id><suffix> with O_CREAT|O_EXCL; True only for the single caller that created it."""
    try:
        os.close(os.open(str(path.with_suffix(suffix)), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
    except OSError:
        return False
    return True


def revoke_receipt(path: Path) -> bool:
    """Revoke via a <id>.revoked tombstone; the receipt JSON is never rewritten. False when no receipt exists."""
    return path.is_file() and _claim(path, ".revoked")


def is_revoked(path: Path) -> bool:
    """True when the revoke tombstone exists."""
    return path.with_suffix(".revoked").exists()


def is_consumed(path: Path) -> bool:
    """True when the single-use marker exists."""
    return path.with_suffix(".consumed").exists()


def consume(path: Path) -> bool:
    """Atomically claim the receipt; exactly one concurrent caller gets True."""
    return _claim(path, ".consumed")


def effective(path: Path) -> dict[str, Any] | None:
    """The receipt with its revoked flag derived from the tombstone, or None when unreadable."""
    data = read_receipt(path)
    return None if data is None else {**data, "revoked": data.get("revoked") is True or is_revoked(path)}


def find_valid(
    session_id: str,
    proposed: dict[str, Any],
    now: datetime,
    loop_id: str | None,
    base: Path | None = None,
    consume_it: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Return (receipt, "ok") for the first receipt in this session that verifies, else (None, refusal code).

    With consume_it a single-use match is claimed atomically; losing the claim race reports "consumed".
    """
    auth = authority_path(session_id, base)
    if auth is None:
        return None, "no_session" if not session_id else "malformed"
    paths = sorted((auth.parent / "receipts").glob("*.json"))
    refusals: list[str] = []
    for path in paths:
        data = effective(path)
        ok, code = verify(data, proposed, now, session_id, loop_id, is_consumed(path))
        if not ok:
            refusals.append(code)
        elif data is not None and data["single_use"] and consume_it and not consume(path):
            refusals.append("consumed")
        elif data is not None:
            return data, "ok"
    return None, next((c for c in refusals if c != "malformed"), refusals[0] if refusals else "no_receipt")
