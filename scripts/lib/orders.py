#!/usr/bin/env python3
"""Standing orders CLI under one lock: exit 0 ok/disabled, 2 refused/error, 3 degraded/pending."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from hooks.scripts.lib import dir_lock  # noqa: E402
from scripts.lib import lessons  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_legacy_import as legacy_import  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.lib.memory_reasons import REASONS  # noqa: E402

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
        return _refuse(str(error) if str(error) in REASONS else "order_state_error")


def sync_order(
    order: dict[str, Any], session: str, quote: str, repo_dir: Path, ledger: ol.Ledger, replace: bool = False
) -> dict[str, Any]:
    """Reconcile current tagged claims before add; the caller holds the one orders lock throughout."""
    lifecycle.check_staged_identity(repo_dir, ledger, order)
    prior = order.get("muninn", {}).get("id")
    claim = _collapse(str(order["lesson"]))
    current = lessons.current(order["id"], session, prior)
    if isinstance(current, ma.Degraded) or current and (not replace or current.claim == claim or not quote.strip()):
        return lessons.metadata(current, prior)
    if not replace and prior:
        return lessons.metadata(None, prior)
    if not quote.strip():
        return lessons.metadata(ma.Degraded("no_user_cite"), prior)
    try:
        rec = ma.Record("repository", "lesson", claim, "", _collapse(quote), ["order", lessons.tag_for(order["id"])])
        rec.confidence, rec.supersedes = "inferred", current.id if current else None
        res: ma.Degraded | ma.Written = ma.resolve_cite(rec, False, session) or ma.add(rec, session)
    except Exception:  # noqa: BLE001  a failed sync retains the prior K-id and reports explicit degradation
        res = ma.Degraded("muninn_error")
    return lessons.metadata(res, prior)


def _exit(field: dict[str, Any]) -> int:
    return 3 if field["state"] == "degraded" else 0


def _prepare(state_dir: Path, prepared: dict[str, Any]) -> None:
    ol.save(lifecycle.preparation_path(state_dir, prepared["binding"]["loop_id"]), prepared)
    lifecycle.observe(state_dir, "orders_prepared", prepared["binding"], lifecycle.sha(prepared))


def _record_row(ledger: ol.Ledger, row: dict[str, Any], binding: dict[str, Any]) -> ol.Ledger:
    """Apply the validated row with its explicit identity and the owned session/loop."""
    fields = {key: row[key] for key in ("scope", "failure_mode")}
    fields.update(session_id=binding["session_id"], loop_id=binding["loop_id"], now=row["ts"])
    fields["lesson_source"] = ol.source_token(row, binding)
    return cast("ol.Ledger", ol.record(ledger, row["id"], row["lesson"], **fields)["ledger"])


def cmd_record(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Prepare a failure observation; apply recurrence only when owned progress is durably complete."""
    order_id = a.id or ol.slug(a.failure_mode)
    if not (a.failure_mode.strip() and a.lesson.strip() and order_id):
        ol.trace("order.record", "refused", "order_blank_field", a.session, a.loop)
        return _refuse("order_blank_field")
    if len(_collapse(a.lesson)) > CLAIM_MAX:
        ol.trace("order.record", "refused", "order_lesson_too_long", a.session, a.loop)
        return _refuse("order_lesson_too_long")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", order_id):
        ol.trace("order.record", "refused", "order_bad_id", a.session, a.loop)
        return _refuse("order_bad_id")

    held: dict[str, Any] = {}

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger | None, dict[str, Any]]:
        state_dir, state, binding = lifecycle.owned(repo_dir, a.session, a.loop)
        lifecycle.observe(state_dir)
        held["complete"] = state["status"] == "complete"
        prepared = lifecycle.prepared(state_dir, binding)
        old: dict[str, Any] = (
            ol.find(ledger, order_id) or next((r for r in prepared["records"] if r["id"] == order_id), None) or {}
        )
        row: dict[str, Any] = {
            "id": order_id,
            "failure_mode": a.failure_mode,
            "lesson": a.lesson,
            "scope": a.scope,
            "ts": ol.now_iso(),
        }
        if any((e["session_id"], e["loop_id"]) == (a.session, a.loop) for e in old.get("evidence", [])):
            row["replaces_source"] = old.get("lesson_source")
        row["muninn"] = sync_order({**old, **row}, a.session, a.quote, repo_dir, ledger, replace=True)
        prepared["records"] = [r for r in prepared["records"] if r["id"] != order_id] + [row]
        _prepare(state_dir, prepared)
        new = None
        if state["status"] == "complete":
            new = ol.set_muninn(_record_row(ledger, row, binding), order_id, row["muninn"])
        return new, {"recorded": new is not None, "prepared": True, "id": order_id, "muninn": row["muninn"]}

    payload, rc = update(repo_dir, change)
    if rc:
        ol.trace("order.record", "refused", payload["reason_code"], a.session, a.loop)
        if held.get("complete") and payload["reason_code"] == "order_state_error":
            return {**payload, "pending_teardown": True, "progress_complete": True}, 3
        return payload, rc
    field = payload["muninn"]
    outcome = {"written": "recorded", "disabled": "disabled"}.get(field["state"], "degraded")
    ol.trace("order.record", outcome, field["reason_code"], a.session, a.loop)
    return payload, _exit(field)


def cmd_prepare(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Bind all staged inputs (including an empty set), observing preparation without lifecycle effects."""

    def change(ledger: ol.Ledger) -> tuple[None, dict[str, Any]]:
        state_dir, prepared = lifecycle.prepare(repo_dir, a.session, a.loop, ledger, a.refresh_from_sha256)
        lifecycle.observe(state_dir)
        binding = prepared["binding"]
        _prepare(state_dir, prepared)
        return None, {"prepared": True, "binding": binding, "evidence_sha256": lifecycle.sha(prepared)}

    payload, rc = update(repo_dir, change)
    ol.trace("order.prepare", "refused" if rc else "prepared", payload.get("reason_code", "ok"), a.session, a.loop)
    return payload, rc


def cmd_tick(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Apply recurrence/tick after durable completion, then observe only the successfully saved ledger."""
    held: dict[str, Any] = {}

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger | None, dict[str, Any]]:
        state_dir, _, binding = lifecycle.owned(repo_dir, a.session, a.loop, complete=True)
        prepared = lifecycle.prepared(state_dir, binding, required=True)
        acknowledged = lifecycle.observe(state_dir, "orders_ticked", binding, lifecycle.sha(prepared), emit=False)
        for row in prepared["records"]:
            lifecycle.check_staged_identity(repo_dir, ledger, row)
        held["approved"] = True
        original, degraded = ledger, ""
        for row in prepared["records"]:
            known = ol.find(ledger, row["id"]) or row
            prior = known["muninn"].get("id") or row["muninn"].get("id")
            if ol.needs_record(known, row, binding, acknowledged is True):
                ledger = _record_row(ledger, row, binding)
            field = lessons.metadata(lessons.current(row["id"], a.session, prior), prior)
            ledger = ol.set_muninn(ledger, row["id"], field)
            if field["state"] == "degraded":
                degraded = field["reason_code"]
        out = ol.tick(ledger, a.loop, ol.now_iso(), session_id=a.session)
        if out["ticked"] or out["ledger"] != original:
            ol.save(repo_dir / "orders.json", out["ledger"])
        payload = {"ticked": out["ticked"], "decayed": out["decayed"]}
        if degraded:
            payload["degraded"] = degraded
        try:
            lifecycle.observe(state_dir, "orders_ticked", binding, lifecycle.sha(prepared))
        except (OSError, ValueError):
            payload.update(pending_teardown=True, reason_code="order_pending_teardown")
        return None, payload

    payload, rc = update(repo_dir, change)
    if rc:
        if held.get("approved"):
            ol.trace("order.tick", "degraded", "order_pending_teardown", a.session, a.loop)
            return {**payload, "pending_teardown": True, "progress_complete": True}, 3
        ol.trace("order.tick", "refused", payload["reason_code"], a.session, a.loop)
        return payload, rc
    if payload.get("pending_teardown"):
        payload["progress_complete"] = True
        ol.trace("order.tick", "degraded", "order_pending_teardown", a.session, a.loop)
        return payload, 3
    if payload.get("degraded"):
        ol.trace("order.tick", "degraded", payload["degraded"], a.session, a.loop)
        return payload, 3
    outcome = "ticked" if payload["ticked"] else "skipped"
    reason = "ok" if payload["ticked"] else "order_already_ticked"
    ol.trace("order.tick", outcome, reason, a.session, a.loop)
    return payload, 0


def cmd_lessons(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Active orders joined with Muninn's current status."""
    return lessons.serve(ol.open_ledger(repo_dir), a.session)


def cmd_render(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Regenerate both views from the ledger, dropping orders Muninn no longer holds as current (when it answers)."""
    with locked(repo_dir):
        if any((repo_dir / name).is_symlink() for name, _ in VIEWS):
            return _refuse("order_wrong_session")
        ledger = ol.open_ledger(repo_dir)
        got = lessons.joined(ledger, include_decayed=True, session=a.session)
        if "degraded" in got:  # no ledger-text fallback: with Muninn down the view could resurrect retracted orders
            ol.trace("order.render", "degraded", got["degraded"], a.session)
            return {"degraded": got["degraded"]}, 3
        keep = got["state"] == "memory_backend_off"
        rows = {r["id"]: r for r in got["lessons"] if keep or r["cited"]}
        shown: ol.Ledger = {
            **ledger,
            "orders": [
                {**o, "lesson": rows[o["id"]]["text"], "muninn": {**o["muninn"], "id": rows[o["id"]]["muninn_id"]}}
                for o in ledger["orders"]
                if o["id"] in rows
            ],
        }
        view_hashes = {}
        for name, decayed in VIEWS:
            content = ol.view(shown, decayed)
            bad = ma.write_view(repo_dir / name, content, a.session)
            if bad:
                ol.trace("order.render", "refused", bad.reason, a.session)
                return {"degraded": bad.reason}, 3
            os.chmod(repo_dir / name, 0o444)
            view_hashes[name] = hashlib.sha256(content.encode()).hexdigest()
        ol.trace("order.render", "rendered", "ok", a.session)
        excluded = sorted({g["order"] for g in got.get("excluded", [])})
        result: dict[str, Any] = {"rendered": [n for n, _ in VIEWS], "excluded": excluded}
        result.update(ledger_sha256=lifecycle.sha(ledger), view_sha256=view_hashes)
        return result, 0


def cmd_import(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Load one hand-written snapshot and archive its bytes without moving the source."""
    src = Path(a.file) if a.file else repo_dir / "standing-orders.md"
    if src.is_symlink() or src.resolve().parent != repo_dir.resolve():
        return _refuse("legacy_parse_error", entry=str(src))
    try:
        raw = src.read_bytes()
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        raw = b""
        text = ""
    if not text.strip() or text.split("\n", 1)[0] == ma.MARKER:
        ol.trace("order.import", "refused", "legacy_missing", a.session)
        return _refuse("legacy_missing")
    try:
        parsed = ol.parse_legacy(text, ol.now_iso())
    except ol.LegacyParseError as error:
        ol.trace("order.import", "refused", "legacy_parse_error", a.session)
        return _refuse("legacy_parse_error", entry=error.entry)

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger | None, dict[str, Any]]:
        if src.is_symlink() or src.read_bytes() != raw:
            raise ValueError("legacy_parse_error")
        return None, legacy_import.apply(repo_dir, raw, text, parsed, ledger)

    payload, rc = update(repo_dir, change)
    if not rc:
        ol.trace("order.import", "imported", "legacy_uncited", a.session)
    return payload, rc


def cmd_cite(a: argparse.Namespace, repo_dir: Path) -> Result:
    """Reconcile/attach a user cite under the same single lock as its ledger save."""

    def change(ledger: ol.Ledger) -> tuple[ol.Ledger, dict[str, Any]]:
        order = ol.find(ledger, a.order_id)
        if order is None:
            raise ValueError("order_not_found")
        field = sync_order(order, a.session, a.quote, repo_dir, ledger)
        return ol.set_muninn(ledger, a.order_id, field), {"id": a.order_id, "muninn": field}

    payload, rc = update(repo_dir, change)
    field = payload.get("muninn", {})
    outcome = "refused" if rc else field["state"]
    reason = payload.get("reason_code", field.get("reason_code"))
    ol.trace("order.cite", outcome, reason, a.session)
    return payload, rc or _exit(field)


def cmd_predicate(a: argparse.Namespace, repo_dir: Path) -> Result:
    """The graduation predicate over this ledger and the retro.json files."""
    return ol.predicate(ol.open_ledger(repo_dir), ol.retro_count(repo_dir)), 0


def build_parser() -> argparse.ArgumentParser:
    """The CLI surface."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", required=True, help="the repo-key dir (grandparent of progress.json)")
    sid = (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CODEX_THREAD_ID")
        or os.environ.get("CODEX_SESSION_ID", "")
    )
    ap.add_argument("--session", default=sid, help="the caller session (cites and trace rows)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--failure-mode", required=True)
    rec.add_argument("--lesson", required=True)
    rec.add_argument("--loop", required=True)
    rec.add_argument("--id", default="")
    rec.add_argument("--scope", choices=ol.SCOPES, default="repo")
    rec.add_argument("--quote", default="", help="verbatim quote of the owner's own prompt (12-300 chars)")
    sub.add_parser("tick").add_argument("--loop", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--loop", required=True)
    prep.add_argument("--refresh-from-sha256", default=None, help="CURRENT preparation's evidence_sha256")
    for name in ("predicate", "lessons"):
        sub.add_parser(name)
    sub.add_parser("render").add_argument("--loop", default="")
    sub.add_parser("import-legacy").add_argument("--file", default="")
    cite = sub.add_parser("cite")
    cite.add_argument("order_id")
    cite.add_argument("--quote", required=True)
    return ap


COMMANDS: dict[str, Callable[[argparse.Namespace, Path], Result]] = {
    "record": cmd_record, "tick": cmd_tick, "predicate": cmd_predicate, "lessons": cmd_lessons,
    "render": cmd_render, "import-legacy": cmd_import, "cite": cmd_cite, "prepare": cmd_prepare,
}  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    """Run one command; print its JSON payload; return the exit code."""
    a = build_parser().parse_args(argv)
    repo_dir = Path(a.dir)
    try:
        payload, rc = COMMANDS[a.cmd](a, repo_dir)
    except ol.ChainError as error:
        payload, rc = _refuse("order_chain_broken", offenders=error.offenders)
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as error:
        payload, rc = _refuse(str(error) if str(error) in REASONS else "order_state_error")
    print(json.dumps(payload, sort_keys=True))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
