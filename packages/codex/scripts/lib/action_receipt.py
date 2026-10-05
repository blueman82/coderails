#!/usr/bin/env python3
"""Action receipts v2: signed approval bound to repository + ref + SHA + exact command.

Pure verify(), atomic single-use consume, no daemon. A receipt is valid only when its ssh-keygen signature
verifies against the trust root (receipt_signing), so an agent that merely writes JSON, or signs with its own
key, is refused. v1/unsigned receipts have no downgrade path.
The signer is whoever holds the passphrase-protected owner key; with the user-tier trust root that is a
cooperating-agent safeguard, not a boundary (see docs/decisions/p3-human-only-minting.md).
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

from scripts.lib import receipt_signing
from scripts.lib.authority_object import authority_path, parse_time, safe_session

FIELDS = (
    "receipt_id",
    "authority_id",
    "session_id",
    "loop_id",
    "action",
    "exact_payload_hash",
    "repository",
    "ref",
    "artifact_sha",
    "nonce",
    "scope",
    "issued_at",
    "expires_at",
    "single_use",
    "revoked",
    "signature",
)
UNSIGNED = ("signature", "revoked")  # revoked is derived from the tombstone, so the signature does not cover it
MAX_RECEIPTS = 50  # per session; also the most files find_valid will parse
MAX_RECEIPT_BYTES = 8192
MAX_SCOPE = 500
REASONS = (
    "ok",
    "signature_missing",
    "signature_invalid",
    "signer_unknown",
    "trust_root_missing",
    "hash_mismatch",
    "repository_mismatch",
    "ref_mismatch",
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


def canonical_hash(argv: list[str], cwd: str, branch: str, repository: str = "", ref: str = "") -> str:
    """sha256 over the canonical JSON of argv, cwd, branch, repository and ref."""
    obj = {"argv": argv, "cwd": cwd, "branch": branch, "repository": repository, "ref": ref}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def proposed_action(
    kind: str, segment: str, cwd: str, branch: str, bind: dict[str, str] | None = None
) -> dict[str, Any]:
    """The action as the hook sees it; bind is action_binding.binding() (None = unknowable, nothing will match)."""
    try:
        argv = shlex.split(segment)
    except ValueError:
        argv = [segment.strip()]
    bind = bind or {}
    repository, ref, sha = bind.get("repository"), bind.get("ref"), bind.get("sha")
    return {
        "action": kind,
        "exact_payload_hash": canonical_hash(argv, cwd, branch, repository or "", ref or ""),
        "repository": repository,
        "ref": ref,
        "artifact_sha": sha,
    }


def body_text(rec: dict[str, Any]) -> str:
    """The canonical text a signature covers: every field except the signature and the derived revoked flag."""
    body = {name: rec[name] for name in FIELDS if name not in UNSIGNED}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def receipt_path(session_id: str, receipt_id: str, base: Path | None = None) -> Path | None:
    """Return <session dir>/receipts/<receipt_id>.json, or None for a path-unsafe id (never sanitised)."""
    auth = authority_path(session_id, base)
    if auth is None or not safe_session(receipt_id):
        return None
    return auth.parent / "receipts" / f"{receipt_id}.json"


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _shape_ok(data: dict[str, Any]) -> bool:
    """Closed field set (an absent signature is allowed here: it is reported as signature_missing)."""
    if not set(FIELDS) - {"signature"} <= set(data) <= set(FIELDS):
        return False
    required = (
        "receipt_id", "session_id", "action", "exact_payload_hash", "repository", "ref", "artifact_sha", "nonce",
    )  # fmt: skip
    optional = all(data[name] is None or _nonempty(data[name]) for name in ("authority_id", "loop_id"))
    flags = data["single_use"] is True and isinstance(data["revoked"], bool)
    times = parse_time(data["expires_at"]) is not None and parse_time(data["issued_at"]) is not None
    return optional and all(_nonempty(data[n]) for n in required) and flags and times and isinstance(data["scope"], str)


def verify(
    rec: object,
    proposed: dict[str, Any],
    now: datetime,
    session_id: str,
    loop_id: str | None,
    consumed: bool = False,
    signers: Path | None = None,
) -> tuple[bool, str]:
    """Pure check of one receipt against one proposed action; returns (ok, stable reason code).

    Order: malformed, signature (missing/invalid/unknown signer/no trust root), revoked, expired, foreign session,
    foreign loop, consumed, kind, hash, repository, ref, sha. `signers` is the trust-root file (None = missing).
    """
    if not isinstance(rec, dict) or not _shape_ok(cast("dict[str, Any]", rec)):
        return False, "malformed"
    data = cast("dict[str, Any]", rec)
    code = receipt_signing.check(body_text(data), data.get("signature"), signers)
    if code != "ok":
        return False, code
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
    for field, code in (
        ("action", "kind_mismatch"), ("exact_payload_hash", "hash_mismatch"), ("repository", "repository_mismatch"),
        ("ref", "ref_mismatch"), ("artifact_sha", "sha_mismatch"),
    ):  # fmt: skip
        if data[field] != proposed.get(field):
            return False, code
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
        if path.stat().st_size > MAX_RECEIPT_BYTES:
            return None
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):  # deeply nested "[[[..." raises RecursionError: still malformed
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


def execute(path: Path) -> bool:
    """Atomically mark the action as about to run (.executed); exactly one caller gets True."""
    return _claim(path, ".executed")


def is_executed(path: Path) -> bool:
    """True when the executed marker exists."""
    return path.with_suffix(".executed").exists()


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
    signers: Path | None = None,
) -> tuple[dict[str, Any] | None, str]:
    """Return (receipt, "ok") for the first receipt in this session that verifies, else (None, refusal code).

    With consume_it a match is claimed atomically; losing the claim race reports "consumed".
    """
    auth = authority_path(session_id, base)
    if auth is None:
        return None, "no_session" if not session_id else "malformed"
    paths = sorted((auth.parent / "receipts").glob("*.json"))[:MAX_RECEIPTS]
    refusals: list[str] = []
    for path in paths:
        data = effective(path)
        ok, code = verify(data, proposed, now, session_id, loop_id, is_consumed(path), signers)
        if not ok:
            refusals.append(code)
        elif data is not None and consume_it and not consume(path):
            refusals.append("consumed")
        elif data is not None:
            return data, "ok"
    return None, next((c for c in refusals if c != "malformed"), refusals[0] if refusals else "no_receipt")
