#!/usr/bin/env python3
"""permits(): the one answer to "may this session take this action under its live authority".

Categories: merge, push_main (hook kind git_push), destructive_shell. A live authority refuses a category it
`denied`; merge also stops once max_prs merges were EXECUTED in the session (.executed markers of any merge receipt,
whatever authority_id it carries, so a pre-minted receipt cannot dodge the cap; consumed-only receipts never reached
gh, so they do not count; 0 = none).
merge and push_main always need a signed receipt, with or without an authority. Returns
{allow, reason, requires_approval, authority_id}. Cooperating-agent safeguard (docs/decisions/e3-authority-object.md).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.lib import action_receipt as ar
from scripts.lib.authority_object import authority_path, read_authority

ALWAYS_APPROVED = ("merge", "push_main")
CATEGORY = {"git_push": "push_main"}  # the hook's operation name -> the authority category
_MISSING = object()


def executed_merges(session_id: str, base: Path | None = None) -> int:
    """Count executed merges for the session across grant renewals."""
    auth = authority_path(session_id, base)
    if auth is None:
        return 0
    count = 0
    for marker in (auth.parent / "receipts").glob("*.executed"):
        data = ar.read_receipt(marker.with_suffix(".json"))
        count += bool(
            data
            and data.get("action") == "merge"
            and marker.with_suffix(".json") == ar.receipt_path(session_id, data.get("receipt_id", ""), base)
        )
    return count


def permits(
    session_id: str, action: str, now: datetime | None = None, base: Path | None = None,
    snapshot: dict[str, Any] | None | object = _MISSING,
) -> dict[str, Any]:  # fmt: skip
    """Decide one action for one session; a missing, torn or expired authority is simply none."""
    action = CATEGORY.get(action, action)
    if snapshot is _MISSING:
        live = read_authority(session_id, base, now)
    else:
        live = None if snapshot is None else cast(dict[str, Any], snapshot)
    needs = action in ALWAYS_APPROVED
    if live is None:
        return {"allow": True, "reason": "no_authority", "requires_approval": needs, "authority_id": None}
    verdict: dict[str, Any] = {
        "allow": True, "reason": "ok", "requires_approval": needs or action in live["approval_required_for"],
        "authority_id": live["authority_id"],
    }  # fmt: skip
    if action in live["denied"]:
        return verdict | {"allow": False, "reason": "authority_denied"}
    if action == "merge" and executed_merges(session_id, base) >= live["max_prs"]:
        return verdict | {"allow": False, "reason": "max_prs_exceeded"}
    return verdict
