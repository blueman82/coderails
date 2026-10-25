#!/usr/bin/env python3
"""Receipt gate for the hook and merge.py, with session-wide merge-budget locking.

Plain gh merges count as executed; absent or unknown config is off.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import action_receipt as ar
from scripts.lib import advisory_merge, merge_budget, merge_hook_note
from scripts.lib.action_binding import binding, git_out
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
    """(mode, bad): only explicit supported values enable the gate."""
    path = config_path(cwd)
    value = config_value(path, "action_authority") if path else ""
    if value in MODES:
        return value, False
    return "off", False


def _record(path: Path, name: str, proposed: dict[str, Any]) -> bool:
    """Write the payload hash and PR number into the .consumed marker; a plain gh merge is marked executed here."""
    note = {"hash": proposed["exact_payload_hash"], "number": proposed.get("number", ""), "action": name}
    path.with_suffix(".consumed").write_text(json.dumps(note), encoding="utf-8")
    if name == "merge" and not proposed.get("script"):
        return ar.execute(path)
    return True


def _check_and_consume(
    session: str, proposals: list[tuple[str, dict[str, Any]]], now: datetime, loop_id: str | None, signers: Path | None,
    consume: bool = True, stale: bool = False, on_claim: Callable[[str], None] | None = None,
) -> tuple[str, str] | None:  # fmt: skip
    """Return a refusal or None; consume=False verifies only; stale means a prior ref mutation."""
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
    seen: set[str] = set()
    for name, proposed in proposals:
        found, code = ar.find_valid(session, proposed, now, loop_id, signers=signers, excluded=seen)
        if found is None:
            return name, code
        seen.add(found["receipt_id"])
    if not consume:
        return None
    actions = [proposed for _, proposed in proposals]
    claimed, code, index = ar.claim_many(session, actions, now, loop_id, signers=signers)
    if claimed is None:
        return proposals[index][0], code
    for (name, proposed), found in zip(proposals, claimed):
        path = ar.receipt_path(session, found["receipt_id"])
        if path is None:
            return name, "malformed"
        if not _record(path, name, proposed):
            return name, "executed_marker_unavailable"
    if on_claim is not None:
        for name, _ in proposals:
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


def require_merge_receipt(
    number: str, cwd: str | None = None, now: datetime | None = None, target: str | None = None,
    verified_sha: str | None = None, expected_sha: str | None = None, command: str | None = None,
) -> Path | None:  # fmt: skip
    """Called once by merge.py before `gh pr merge`; returns only when a receipt was claimed (or mode allows)."""
    cwd = cwd or os.getcwd()
    if expected_sha is not None and expected_sha != verified_sha:
        raise ReceiptRefusedError("expected_head_mismatch")
    mode, _ = resolve_mode(cwd)
    if mode == "off":
        return None
    session = next((os.environ[name] for name in SESSION_ENV if os.environ.get(name)), "")
    code = _claim_merge(session, number, cwd, now, command)
    if code == "ok":
        return None
    reservation_required = False
    if mode == "advisory" and code not in {"authority_denied", "max_prs_exceeded"}:
        reservation_required, reserved, path = advisory_merge.direct(
            session, number, cwd, target, verified_sha, command
        )
        if path:
            append_row("action_authority", "advisory", f"merge_py_{code}", session)
            return path
        if reservation_required:
            code = reserved
    outcome = "advisory" if mode == "advisory" and code not in {"authority_denied", "max_prs_exceeded"} else "denied"
    append_row("action_authority", outcome, f"merge_py_{code}", session or "_no_session")
    if code in {"authority_denied", "max_prs_exceeded"} or reservation_required:
        raise ReceiptRefusedError(f"merge refused by live session authority ({code})")
    if mode == "enforce":
        raise ReceiptRefusedError(f"merge needs a signed owner receipt ({code}); use approve-action")
    return None


def _claim_merge(
    session: str, number: str, cwd: str, now: datetime | None, command: str | None = None,
) -> str:  # fmt: skip
    if not session:
        return "no_session"
    with merge_budget.lock(session) as acquired:
        if not acquired:
            return "budget_lock_unavailable"
        return _claim_merge_unlocked(session, number, cwd, now or datetime.now(timezone.utc), command)


def _claim_merge_unlocked(
    session: str, number: str, cwd: str, now: datetime, command: str | None = None,
) -> str:  # fmt: skip
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
    if command is None:
        return "binding_unknown"
    bind = binding("merge", command, cwd)
    if bind is None:
        return "binding_unknown"
    direct = ar.proposed_action("merge", command, cwd, git_out(cwd, "branch", "--show-current"), bind)
    loop_id = authority["loop_id"] if authority else None
    signers = resolve_trust_root()[0]
    refusals: list[str] = []
    for path in sorted((auth.parent / "receipts").glob("*.json"))[: ar.MAX_RECEIPTS]:
        data = ar.read_receipt(path)
        if data is None or path != ar.receipt_path(session, data.get("receipt_id", "")):
            refusals.append("malformed")
            continue
        data["revoked"] = data.get("revoked") is True or ar.is_revoked(path)
        note = merge_hook_note.fresh(path, number, HOOK_WINDOW_S)
        proposed = direct if note is None else {**direct, "exact_payload_hash": note["hash"]}
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
