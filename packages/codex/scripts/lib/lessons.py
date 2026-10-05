#!/usr/bin/env python3
"""Lessons for dispatch and promotion: the standing orders joined with Muninn's CURRENT status (provider-neutral).

    lessons.py --dir <repo-key dir> query --format contract   stable, sorted, verbatim list for contract.lessons[]
    lessons.py --dir <repo-key dir> predicate                 promotion selection: graduation result + candidates

Only active, non-decayed orders are served. An order written to Muninn is served with Muninn's text, K-id and cite, and
is excluded (and traced `lesson.query/excluded/lesson_not_current`) when its entry is retracted, expired or superseded
with no current replacement; a current entry carrying the order's own `ord-` tag replaces it. With Muninn down this
exits 3 with the reason and prints NO ledger text (`memory.backend: off` is the explicit switch: ledger text, exit 0).
Orders that never reached Muninn (no cite yet, legacy import) are served flagged `cited: false`.
Exit 0 ok, 2 refused, 3 degraded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402

TAG_MAX = 32  # muninn's tag rule


def tag_for(order_id: str) -> str:
    """The Muninn tag `ord-<id>`, shortened with a hash when the id would overflow the 32-char tag limit."""
    if len("ord-" + order_id) <= TAG_MAX:
        return "ord-" + order_id
    return f"ord-{order_id[:TAG_MAX - 13]}-{hashlib.sha1(order_id.encode()).hexdigest()[:8]}"  # noqa: S324


def _row(order: dict[str, Any], rec: ma.Record | None) -> dict[str, Any]:
    cited = rec is not None
    return {
        "id": order["id"],
        "text": rec.claim if rec else order["lesson"],
        "cited": cited,
        "cite": rec.cite if rec else "",
        "quote": rec.quote if rec else "",
        "muninn_id": rec.id if rec else None,
        "scope": order["scope"],
    }


def joined(ledger: ol.Ledger) -> dict[str, Any]:
    """{"lessons", "excluded"} for the active orders, or {"degraded": reason} (no text) when Muninn cannot answer."""
    active = sorted((o for o in ledger["orders"] if o["status"] == "active"), key=lambda o: str(o["id"]))
    if ma.backend() == "off":
        return {"lessons": [_row(o, None) for o in active], "excluded": [], "state": "memory_backend_off"}
    down = ma.probe()
    if down:
        return {"degraded": down.reason}
    listed = ma.list_records("repository", type="lesson", tags=["order"])
    if isinstance(listed, ma.Degraded):
        return {"degraded": listed.reason}
    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for order in active:
        if order["muninn"].get("state") != "written":  # never reached Muninn: served, flagged uncited
            rows.append(_row(order, None))
            continue
        mine = [r for r in listed if tag_for(order["id"]) in r.tags]
        exact = [r for r in mine if r.id == order["muninn"].get("id")]
        pick = exact[0] if exact else max(mine, key=lambda r: int(str(r.id)[1:]), default=None)
        if pick is None:
            excluded.append({"order": order["id"], "reason": "lesson_not_current"})
        else:
            rows.append(_row(order, pick))
    return {"lessons": rows, "excluded": excluded, "state": "muninn"}


def serve(ledger: ol.Ledger, session: str) -> tuple[dict[str, Any], int]:
    """Joined + trace rows (one per exclusion, one for the query); returns (payload, exit code)."""
    got = joined(ledger)
    if "degraded" in got:
        ol.trace("lesson.query", "degraded", got["degraded"], session)
        return {"degraded": got["degraded"]}, 3
    for gone in got["excluded"]:
        ol.trace("lesson.query", "excluded", gone["reason"], session)
    ol.trace("lesson.query", "served", got["state"] if got["state"] != "muninn" else "ok", session)
    return got, 0


def contract(payload: dict[str, Any]) -> dict[str, Any]:
    """The dispatch list: rows sorted by order id, plus the sha256 of their canonical JSON."""
    rows = sorted(payload["lessons"], key=lambda r: str(r["id"]))
    return {"lessons": rows, "sha256": hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def selection(ledger: ol.Ledger, repo_dir: Path) -> dict[str, Any]:
    """Graduation result plus the promotion candidates (agnostic, >= 2 recurrences, >= 2 distinct sessions)."""
    picked = [
        {
            "id": o["id"],
            "failure_mode": o["failure_mode"],
            "lesson": o["lesson"],
            "recurrences": len(o["evidence"]) - 1,
            "sessions": sorted({e["session_id"] for e in o["evidence"]}),
        }
        for o in ol.candidates(ledger)
    ]
    return {"graduation": ol.predicate(ledger, ol.retro_count(repo_dir)), "candidates": picked}


def main(argv: list[str] | None = None) -> int:
    """CLI: query|predicate."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, help="the repo-key dir holding orders.json")
    ap.add_argument(
        "--session", default=os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("query").add_argument("--format", choices=("contract",), default="contract")
    sub.add_parser("predicate")
    a = ap.parse_args(argv)
    repo_dir = Path(a.dir)
    try:
        ledger = ol.open_ledger(repo_dir)
    except ol.ChainError as error:
        print(json.dumps({"reason_code": "order_chain_broken", "offenders": error.offenders}))
        return 2
    except ValueError:
        print(json.dumps({"reason_code": "order_state_error"}))
        return 2
    if a.cmd == "predicate":
        out = selection(ledger, repo_dir)
        ol.trace("lesson.predicate", "met" if out["graduation"]["met"] else "unmet", "ok", a.session)
        print(json.dumps(out, sort_keys=True))
        return 0
    payload, rc = serve(ledger, a.session)
    print(json.dumps(payload if rc else contract(payload), sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
