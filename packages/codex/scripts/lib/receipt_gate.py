#!/usr/bin/env python3
"""The shared receipt gate: the PreToolUse hook and scripts/merge.py both go through here.

Two-phase, exactly once. Phase 1 (hook): check_and_consume() refuses on authority.permits() first (nothing consumed),
then verifies every guarded segment and claims each receipt (.consumed, O_EXCL) and records its payload hash and PR
number in that marker. A plain `gh pr merge` is also marked .executed there (nothing later runs it for us).
Phase 2 (merge.py): require_merge_receipt() accepts a receipt the hook consumed for this PR within 300 s whose
repository+ref+SHA still match the live PR, and claims .executed (O_EXCL) before `gh pr merge`. If no hook ran it
verifies and consumes a signed receipt itself. Fail-closed: no session, binding or receipt raises ReceiptRefusedError.
Mode `action_authority`: enforce (default, also with no config) | advisory | off; anything else is enforce
(action_authority_bad_mode). Cooperating-agent safeguard, see docs/decisions/p3-human-only-minting.md.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import action_receipt as ar
from scripts.lib.action_binding import binding
from scripts.lib.authority_object import append_row, authority_path, read_authority
from scripts.lib.authority_permits import permits
from scripts.lib.config import config_path, config_value
from scripts.lib.receipt_signing import resolve_trust_root

HOOK_WINDOW_S = 300
SESSION_ENV = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")
MODES = ("enforce", "advisory", "off")


class ReceiptRefusedError(ValueError):
    """A stable reason code; merge.py's main() prints it and exits 1."""


def resolve_mode(cwd: str) -> tuple[str, bool]:
    """(mode, bad): enforce when the key or the whole config is absent; an unrecognised value is enforce, bad=True."""
    path = config_path(cwd)
    value = config_value(path, "action_authority") if path else ""
    if value in MODES:
        return value, False
    return "enforce", bool(value)


def _record(path: Path, name: str, proposed: dict[str, Any]) -> None:
    """Write the payload hash and PR number into the .consumed marker; a plain gh merge is marked executed here."""
    note = {"hash": proposed["exact_payload_hash"], "number": proposed.get("number", ""), "action": name}
    path.with_suffix(".consumed").write_text(json.dumps(note), encoding="utf-8")
    if name == "merge" and not proposed.get("script"):
        ar.execute(path)


def check_and_consume(
    session: str,
    proposals: list[tuple[str, dict[str, Any]]],
    now: datetime,
    loop_id: str | None,
    signers: Path | None,
    consume: bool = True,
    stale: bool = False,
) -> tuple[str, str] | None:
    """None when every (name, proposed) segment is allowed, else (name, reason code). consume=False only verifies.

    stale: a ref/HEAD/remote-moving step precedes the guarded one, so the bound sha/ref would be out of date.
    """
    for name, _ in proposals:
        verdict = permits(session, name, now)
        if not verdict["allow"]:
            return name, str(verdict["reason"])
    unbound = next((name for name, proposed in proposals if proposed["artifact_sha"] is None), None)
    if unbound:
        return unbound, "binding_unknown"  # unknowable repository+ref+sha fails closed
    if stale:
        return proposals[0][0], "state_mutated_before_guard"
    for name, proposed in proposals:
        found, code = ar.find_valid(session, proposed, now, loop_id, signers=signers)
        if found is None:
            return name, code
    if not consume:
        return None
    for name, proposed in proposals:  # the O_EXCL claim, not the verify above, decides who is allowed
        found, code = ar.find_valid(session, proposed, now, loop_id, consume_it=True, signers=signers)
        path = ar.receipt_path(session, found["receipt_id"]) if found else None
        if path is None:
            return name, code
        _record(path, name, proposed)
    return None


def _fresh_hook_note(path: Path, number: str) -> dict[str, Any] | None:
    """The hook's note in .consumed when it is recent, names this PR and the receipt is not yet executed."""
    marker = path.with_suffix(".consumed")
    try:
        raw: object = json.loads(marker.read_text(encoding="utf-8"))
        recent = time.time() - marker.stat().st_mtime <= HOOK_WINDOW_S
    except (OSError, ValueError):
        return None
    note = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
    return note if note.get("number") == number and recent and not ar.is_executed(path) else None


def require_merge_receipt(number: str, cwd: str | None = None, now: datetime | None = None) -> None:
    """Called once by merge.py before `gh pr merge`; returns only when a receipt was claimed (or mode allows)."""
    cwd = cwd or os.getcwd()
    mode, _ = resolve_mode(cwd)
    if mode == "off":
        return
    session = next((os.environ[name] for name in SESSION_ENV if os.environ.get(name)), "")
    now = now or datetime.now(timezone.utc)
    code = _claim_merge(session, number, cwd, now)
    if code == "ok":
        return
    outcome = "advisory" if mode == "advisory" else "denied"
    append_row("action_authority", outcome, f"merge_py_{code}", session or "_no_session")
    if mode == "enforce":
        raise ReceiptRefusedError(
            f"merge needs a signed owner receipt ({code}); owner mints it: scripts/action_receipt_cli.py approve-action"
        )


def _claim_merge(session: str, number: str, cwd: str, now: datetime) -> str:
    """Return ok after claiming .executed for one matching receipt, else the refusal code."""
    auth = authority_path(session)
    if not session or auth is None:
        return "no_session"
    verdict = permits(session, "merge", now)
    if not verdict["allow"]:
        return str(verdict["reason"])
    bind = binding("merge", f"python3 scripts/merge.py {number}", cwd)  # merge.py pins the head sha it verified
    if bind is None:
        return "binding_unknown"
    authority = read_authority(session, now=now)
    loop_id = authority["loop_id"] if authority else None
    signers = resolve_trust_root()[0]
    refusals: list[str] = []
    for path in sorted((auth.parent / "receipts").glob("*.json"))[: ar.MAX_RECEIPTS]:
        data = ar.effective(path)
        note = _fresh_hook_note(path, number)
        proposed = {
            "action": "merge", "repository": bind["repository"], "ref": bind["ref"], "artifact_sha": bind["sha"],
            "exact_payload_hash": note["hash"] if note else (data or {}).get("exact_payload_hash"),
        }  # fmt: skip
        consumed = ar.is_consumed(path) and note is None
        ok, why = ar.verify(data, proposed, now, session, loop_id, consumed, signers)
        if not ok:
            refusals.append(why)
        elif (note is None and not ar.consume(path)) or not ar.execute(path):
            refusals.append("consumed")
        else:
            append_row("action_authority", "allowed", "merge_py_receipt_executed", session, loop_id)
            return "ok"
    return next((c for c in refusals if c != "malformed"), refusals[0] if refusals else "no_receipt")
