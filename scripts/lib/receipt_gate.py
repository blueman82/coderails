#!/usr/bin/env python3
"""Shared hook/merge.py receipt gate, with a session-wide merge-budget lock.

The hook checks permits and bindings before O_EXCL consumption; plain gh merges count as executed.
merge.py checks a recent hook claim or consumes directly, then claims execution before gh pr merge.
Absent action_authority config is advisory; an invalid value enforces.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import action_receipt as ar
from scripts.lib import merge_budget
from scripts.lib.action_binding import binding
from scripts.lib.authority_object import append_row, authority_path, read_authority
from scripts.lib.authority_permits import executed_merges, permits
from scripts.lib.config import config_path, config_value
from scripts.lib.receipt_signing import resolve_trust_root

HOOK_WINDOW_S = 300
SESSION_ENV = ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")
MODES = ("enforce", "advisory", "off")


class ReceiptRefusedError(ValueError):
    """A stable reason code; merge.py's main() prints it and exits 1."""


def resolve_mode(cwd: str) -> tuple[str, bool]:
    """(mode, bad): warn by default; fail closed for an unrecognised value."""
    path = config_path(cwd)
    value = config_value(path, "action_authority") if path else ""
    if value in MODES:
        return value, False
    return ("enforce", True) if value else ("advisory", False)


def _record(path: Path, name: str, proposed: dict[str, Any]) -> None:
    """Write the payload hash and PR number into the .consumed marker; a plain gh merge is marked executed here."""
    note = {"hash": proposed["exact_payload_hash"], "number": proposed.get("number", ""), "action": name}
    path.with_suffix(".consumed").write_text(json.dumps(note), encoding="utf-8")
    if name == "merge" and not proposed.get("script"):
        ar.execute(path)


def _check_and_consume(
    session: str,
    proposals: list[tuple[str, dict[str, Any]]],
    now: datetime,
    loop_id: str | None,
    signers: Path | None,
    consume: bool = True,
    stale: bool = False,
    on_claim: Callable[[str], None] | None = None,
) -> tuple[str, str] | None:
    """None when every (name, proposed) segment is allowed, else (name, reason code). consume=False only verifies.

    stale: a ref/HEAD/remote-moving step precedes the guarded one, so the bound sha/ref would be out of date.
    """
    live = read_authority(session, now=now)
    for name, _ in proposals:
        verdict = permits(session, name, now, snapshot=live)
        if not verdict["allow"]:
            return name, str(verdict["reason"])
        if not verdict.get("requires_approval", False):
            return name, "approval_requirement_missing"
    loop_id = live["loop_id"] if live else None
    plain_merges = sum(name == "merge" and not proposed.get("script") for name, proposed in proposals)
    if live and executed_merges(session) + plain_merges > live["max_prs"]:
        return "merge", "max_prs_exceeded"
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
        if name == "merge":
            verdict = permits(session, name, now, snapshot=live)
            if not verdict["allow"]:
                return name, str(verdict["reason"])
        found, code = ar.find_valid(session, proposed, now, loop_id, consume_it=True, signers=signers)
        path = ar.receipt_path(session, found["receipt_id"]) if found else None
        if path is None:
            return name, code
        _record(path, name, proposed)
        if on_claim is not None:
            on_claim(name)
    return None


def check_and_consume(
    session: str, proposals: list[tuple[str, dict[str, Any]]], now: datetime | None, loop_id: str | None,
    signers: Path | None, consume: bool = True, stale: bool = False,
    on_claim: Callable[[str], None] | None = None,
) -> tuple[str, str] | None:  # fmt: skip
    """Check receipt and grant together; serialize merge budgets with execution claims."""
    if any(name == "merge" for name, _ in proposals):
        with merge_budget.lock(session) as acquired:
            if not acquired:
                return "merge", "budget_lock_unavailable"
            effective_now = now or datetime.now(timezone.utc)
            return _check_and_consume(session, proposals, effective_now, loop_id, signers, consume, stale, on_claim)
    return _check_and_consume(
        session, proposals, now or datetime.now(timezone.utc), loop_id, signers, consume, stale, on_claim
    )


def _fresh_hook_note(path: Path, number: str) -> dict[str, Any] | None:
    """The hook's note in .consumed when it is recent, names this PR and the receipt is not yet executed."""
    marker = path.with_suffix(".consumed")
    try:
        raw: object = json.loads(marker.read_text(encoding="utf-8"))
        recent = time.time() - marker.stat().st_mtime <= HOOK_WINDOW_S
    except (OSError, ValueError, RecursionError):
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
    code = _claim_merge(session, number, cwd, now)
    if code == "ok":
        return
    outcome = "advisory" if mode == "advisory" else "denied"
    append_row("action_authority", outcome, f"merge_py_{code}", session or "_no_session")
    if mode == "enforce":
        raise ReceiptRefusedError(
            f"merge needs a signed owner receipt ({code}); owner mints it: scripts/action_receipt_cli.py approve-action"
        )


def _claim_merge(session: str, number: str, cwd: str, now: datetime | None) -> str:
    """Serialize the cap check and executed marker for a direct merge."""
    if not session:
        return "no_session"
    with merge_budget.lock(session) as acquired:
        if not acquired:
            return "budget_lock_unavailable"
        return _claim_merge_unlocked(session, number, cwd, now or datetime.now(timezone.utc))


def _claim_merge_unlocked(session: str, number: str, cwd: str, now: datetime) -> str:
    """Return ok after claiming .executed for one matching receipt, else the refusal code."""
    auth = authority_path(session)
    if not session or auth is None:
        return "no_session"
    authority = read_authority(session, now=now)
    verdict = permits(session, "merge", now, snapshot=authority)
    if not verdict["allow"]:
        return str(verdict["reason"])
    if not verdict.get("requires_approval", False):
        return "approval_requirement_missing"
    bind = binding("merge", f"python3 scripts/merge.py {number}", cwd)  # merge.py pins the head sha it verified
    if bind is None:
        return "binding_unknown"
    loop_id = authority["loop_id"] if authority else None
    signers = resolve_trust_root()[0]
    refusals: list[str] = []
    for path in sorted((auth.parent / "receipts").glob("*.json"))[: ar.MAX_RECEIPTS]:
        data = ar.read_receipt(path)
        if data is None or path != ar.receipt_path(session, data.get("receipt_id", "")):
            refusals.append("malformed")
            continue
        data["revoked"] = data.get("revoked") is True or ar.is_revoked(path)
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
