#!/usr/bin/env python3
"""Standing orders CLI: record|tick|predicate|lessons|render|import-legacy|cite (provider-neutral).

    orders.py --dir D record --failure-mode FM --lesson TEXT --loop LOOP [--quote Q] [--scope repo|agnostic]
    orders.py --dir D tick --loop LOOP    count one loop; non-recorded orders gain 1, decay at K=5
    orders.py --dir D predicate           the graduation predicate (retro.json count, recurred, decayed)
    orders.py --dir D lessons             active orders joined with Muninn's current status (exit 3 if down)
    orders.py --dir D render              regenerate standing-orders.md / -decayed.md (0444, marker-stamped)
    orders.py --dir D import-legacy       load the hand-written standing-orders.md, move it aside
    orders.py --dir D cite ID --quote Q   attach the user-anchored cite to an order stored without one

D is the repo-key dir. The ledger `orders.json` (counters, decay, hash chain; see orders_ledger.py) is written under
dir_lock; the cited claim is synced to Muninn outside the lock as a `lesson` tagged `order` and `ord-<id>`. A degrade
never loses the order: it is kept active with `muninn.state=degraded` and the reason (`no_user_cite` without --quote).
Exit 0 ok or disabled, 2 refused (nothing written, reason_code printed), 3 degraded (reason printed, ledger written).
Never falls back to Markdown.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from hooks.scripts.lib import dir_lock  # noqa: E402
from scripts.lib import lessons  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402

CLAIM_MAX = 500  # muninn's claim length rule
VIEWS = (("standing-orders.md", False), ("standing-orders-decayed.md", True))
Result = tuple[dict[str, Any], int]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _refuse(reason: str, **extra: Any) -> Result:  # noqa: ANN401
    return {"reason_code": reason, **extra}, 2


@contextlib.contextmanager
def locked(repo_dir: Path) -> Generator[None]:
    """Hold dir_lock on <dir>/orders.lock; raises ValueError('lock') when it cannot be taken."""
    lock = repo_dir / "orders.lock"
    got, _ = dir_lock.acquire_dir_lock(lock)
    if not got:
        raise ValueError("lock")
    try:
        yield
    finally:
        dir_lock.release_dir_lock(lock)


def update(repo_dir: Path, change: Callable[[ol.Ledger], tuple[ol.Ledger | None, dict[str, Any]]]) -> Result:
    """Open the ledger under the lock, apply `change` -> (new ledger or None, payload), save. Refusals are exit 2."""
    try:
        with locked(repo_dir):
            ledger = ol.open_ledger(repo_dir)
            new, payload = change(ledger)
            if new is not None:
                ol.save(repo_dir / "orders.json", new)
            return payload, 0
    except ol.ChainError as error:
        return _refuse("order_chain_broken", offenders=error.offenders)
    except (ValueError, OSError) as error:
        return _refuse("order_not_found" if str(error) == "order_not_found" else "order_state_error")


def sync_order(order: dict[str, Any], session: str, quote: str) -> dict[str, Any]:
    """Write the lesson to Muninn; returns the muninn field {id, state written|degraded|disabled, reason_code}."""
    if ma.backend() == "off":
        return {"id": None, "state": "disabled", "reason_code": "memory_backend_off"}
    if not quote.strip():
        return {"id": None, "state": "degraded", "reason_code": "no_user_cite"}
    claim = _collapse(str(order["lesson"]))
    claim = claim if len(claim) <= CLAIM_MAX else claim[: CLAIM_MAX - 1] + "…"
    rec = ma.Record("repository", "lesson", claim, "", _collapse(quote), ["order", lessons.tag_for(order["id"])])
    rec.confidence = "inferred"
    try:
        res: ma.Degraded | ma.Written = ma.resolve_cite(rec, False, session) or ma.add(rec, session)
    except Exception:  # noqa: BLE001  a crash is a degrade; the ledger row is already safe
        res = ma.Degraded("muninn_error")
    if isinstance(res, ma.Written):
        return {"id": res.id, "state": "written", "reason_code": "ok"}
    return {"id": None, "state": "degraded", "reason_code": res.reason}


def _store(repo_dir: Path, order_id: str, field: dict[str, Any]) -> Result:
    return update(repo_dir, lambda ledger: (ol.set_muninn(ledger, order_id, field), {}))


def _exit(field: dict[str, Any]) -> int:
    return 3 if field["state"] == "degraded" else 0


def cmd_record(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Record a new order or a recurrence, then sync it to Muninn unless it is already written."""
    order_id = a.id or ol.slug(a.failure_mode)
    if not (a.failure_mode.strip() and a.lesson.strip() and order_id):
        ol.trace("order.record", "refused", "order_blank_field", a.session, a.loop)
        return _refuse("order_blank_field")
    held: dict[str, Any] = {}

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger | None, dict[str, Any]]:
        out = ol.record(
            ledger, order_id, a.lesson, session_id=a.evidence_session or a.session or "unknown", loop_id=a.loop,
            now=ol.now_iso(), scope=a.scope, failure_mode=a.failure_mode,
        )  # fmt: skip
        held.update(out["order"])
        return out["ledger"], {}

    payload, rc = update(repo_dir, change)
    if rc:
        ol.trace("order.record", "refused", payload["reason_code"], a.session, a.loop)
        return payload, rc
    field = held["muninn"]
    if field.get("state") != "written":
        field = sync_order(held, a.session, a.quote)
        payload, rc = _store(repo_dir, order_id, field)
        if rc:
            return payload, rc
    outcome = {"written": "recorded", "disabled": "disabled"}.get(field["state"], "degraded")
    ol.trace("order.record", outcome, field["reason_code"], a.session, a.loop)
    return {"recorded": True, "id": order_id, "muninn": field}, _exit(field)


def cmd_tick(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Count one loop (idempotent per loop id)."""
    held: dict[str, Any] = {}

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger | None, dict[str, Any]]:
        out = ol.tick(ledger, a.loop, ol.now_iso())
        held.update(out)
        return (out["ledger"] if out["ticked"] else None), {}

    payload, rc = update(repo_dir, change)
    if rc:
        ol.trace("order.tick", "refused", payload["reason_code"], a.session, a.loop)
        return payload, rc
    ol.trace(
        "order.tick",
        "ticked" if held["ticked"] else "skipped",
        "ok" if held["ticked"] else "order_already_ticked",
        a.session,
        a.loop,
    )
    return {"ticked": held["ticked"], "decayed": held["decayed"]}, 0


def cmd_lessons(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Active orders joined with Muninn's current status."""
    payload, rc = lessons.serve(ol.open_ledger(repo_dir), a.session)
    return payload, rc


def cmd_render(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Regenerate both views from the ledger, dropping orders Muninn no longer holds as current (when it answers)."""
    ledger = ol.open_ledger(repo_dir)
    got = lessons.joined(ledger)
    gone = {g["order"] for g in got.get("excluded", [])}
    shown: ol.Ledger = {**ledger, "orders": [o for o in ledger["orders"] if o["id"] not in gone]}
    for name, decayed in VIEWS:
        bad = ma.write_view(repo_dir / name, ol.view(shown, decayed), a.session)
        if bad:
            ol.trace("order.render", "refused", bad.reason, a.session)
            return {"degraded": bad.reason}, 3
        os.chmod(repo_dir / name, 0o444)
    ol.trace("order.render", "rendered", "ok", a.session)
    return {"rendered": [n for n, _ in VIEWS], "excluded": sorted(gone)}, 0


def cmd_import(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Load the hand-written file into the ledger (legacy_uncited), then move it aside."""
    src = Path(a.file) if a.file else repo_dir / "standing-orders.md"
    try:
        text = src.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if not text.strip() or text.split("\n", 1)[0] == ma.MARKER:
        ol.trace("order.import", "refused", "legacy_missing", a.session)
        return _refuse("legacy_missing")
    try:
        parsed = ol.parse_legacy(text, ol.now_iso())
    except ol.LegacyParseError as error:
        ol.trace("order.import", "refused", "legacy_parse_error", a.session)
        return _refuse("legacy_parse_error", entry=error.entry)
    count = {"imported": 0}

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger | None, dict[str, Any]]:
        new = {**ledger, "orders": list(ledger["orders"])}
        have = {o["id"] for o in new["orders"]}
        fresh = [o for o in parsed if o["id"] not in have]
        new["orders"] += fresh
        count["imported"] = len(fresh)
        return ol.seal(new), {}

    payload, rc = update(repo_dir, change)
    if rc:
        return payload, rc
    dest = repo_dir / "standing-orders.legacy.md"
    for n in range(2, 1000):
        if not dest.exists():
            break
        dest = repo_dir / f"standing-orders.legacy.{n}.md"
    os.replace(src, dest)
    ol.trace("order.import", "imported", "legacy_uncited", a.session)
    return {"imported": count["imported"], "skipped": len(parsed) - count["imported"], "moved_to": str(dest)}, 0


def cmd_cite(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Attach the user-anchored cite to an order that has none (a written order is left alone)."""
    order = ol.find(ol.open_ledger(repo_dir), a.order_id)
    if order is None:
        ol.trace("order.cite", "refused", "order_not_found", a.session)
        return _refuse("order_not_found")
    if order["muninn"].get("state") == "written":
        return {"id": a.order_id, "muninn": order["muninn"]}, 0
    field = sync_order(order, a.session, a.quote)
    payload, rc = _store(repo_dir, a.order_id, field)
    ol.trace("order.cite", "cited" if field["state"] == "written" else field["state"], field["reason_code"], a.session)
    return ({"id": a.order_id, "muninn": field}, _exit(field)) if not rc else (payload, rc)


def cmd_predicate(a: argparse.Namespace, repo_dir: Path) -> Result:
    """The graduation predicate over this ledger and the retro.json files."""
    return ol.predicate(ol.open_ledger(repo_dir), ol.retro_count(repo_dir)), 0


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="the repo-key dir (grandparent of progress.json)")
    sid = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    ap.add_argument("--session", default=sid, help="the caller session (cites and trace rows)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--failure-mode", required=True)
    rec.add_argument("--lesson", required=True)
    rec.add_argument("--loop", required=True)
    rec.add_argument("--id", default="")
    rec.add_argument("--scope", choices=ol.SCOPES, default="repo")
    rec.add_argument("--quote", default="", help="verbatim quote of the owner's own prompt (12-300 chars)")
    rec.add_argument("--evidence-session", default="", help="session id recorded as evidence (default: --session)")
    sub.add_parser("tick").add_argument("--loop", required=True)
    for name in ("predicate", "lessons", "render"):
        sub.add_parser(name)
    sub.add_parser("import-legacy").add_argument("--file", default="")
    cite = sub.add_parser("cite")
    cite.add_argument("order_id")
    cite.add_argument("--quote", required=True)
    return ap


COMMANDS: dict[str, Callable[[argparse.Namespace, Path], Result]] = {
    "record": cmd_record, "tick": cmd_tick, "predicate": cmd_predicate, "lessons": cmd_lessons,
    "render": cmd_render, "import-legacy": cmd_import, "cite": cmd_cite,
}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    """Run one command; print its JSON payload; return the exit code."""
    a = build_parser().parse_args(argv)
    repo_dir = Path(a.dir)
    try:
        payload, rc = COMMANDS[a.cmd](a, repo_dir)
    except ol.ChainError as error:
        payload, rc = _refuse("order_chain_broken", offenders=error.offenders)
    except (ValueError, OSError):
        payload, rc = _refuse("order_state_error")
    print(json.dumps(payload, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
