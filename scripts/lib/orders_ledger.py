#!/usr/bin/env python3
"""Standing orders as typed records: the pure model, a hash chain over the orders, atomic file IO (provider-neutral).

An order is `{id, created, failure_mode, lesson, evidence[{session_id, loop_id, ts}], last_recurred,
loops_since_recurrence, status active|decayed, decayed_at, scope repo|agnostic, muninn{id, state, reason_code}}`
plus the chain fields `{seq, prev_sha256, row_sha256}`. `row_sha256` covers every field except `muninn` and itself,
and `prev_sha256` names the previous order's hash (64 zeros first), so a hand edit or a dropped or swapped middle order
is named by `verify`. A `head` {count, last_sha256, ticks_sha256} anchors the tail and the ticked loops, so a dropped
last order or edited ticks are named too (`#ledger`/`bad_head`). Every writer here recomputes the whole chain (`seal`)
because ticks change every order. Cooperating-agent safeguard, not a security boundary: a same-user agent can rewrite
the file and recompute chain and head, and an absent file beside no generated view loads as an empty ledger;
`muninn` sits outside the hash. The counters and decay live here; the cited claim lives in Muninn
(see lessons.py, orders.py).
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import re
import runpy
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.lib.memory_adapter import MARKER, NO_SESSION  # noqa: E402

K = 5  # a loop count, deliberately a code constant and not config: an order decays after K loops without recurrence
GENESIS = "0" * 64
HASH_EXCLUDED = ("row_sha256", "muninn")
RETRO_MIN = 10  # the graduation predicate's retro.json floor
SCOPES = ("repo", "agnostic")
Ledger = dict[str, Any]


def now_iso() -> str:
    """UTC timestamp to the microsecond, so a recurrence is never equal to its creation stamp."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="microseconds")


def slug(text: str) -> str:
    """Preserve canonical ids; hash free text so normalization cannot merge distinct failure modes."""
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", text) and len(text) <= 120:
        return text
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:107] or "order"
    return f"{base}-{hashlib.sha256(text.encode()).hexdigest()[:12]}"


def empty() -> Ledger:
    """A new (sealed) ledger."""
    return seal({"schema": 1, "orders": [], "ticked_loops": []})


def digest(order: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the order minus `muninn` and `row_sha256`."""
    body = {k: v for k, v in order.items() if k not in HASH_EXCLUDED}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _head(ledger: Ledger, last: str) -> dict[str, Any]:
    """The anchor over the whole ledger: order count, last row hash and a hash of the ticked loops."""
    ticks = json.dumps(ledger.get("ticked_loops", []), separators=(",", ":")).encode("utf-8")
    return {"count": len(ledger["orders"]), "last_sha256": last, "ticks_sha256": hashlib.sha256(ticks).hexdigest()}


def seal(ledger: Ledger) -> Ledger:
    """Renumber and rehash the chain in place and re-anchor the head (the writer-side step every mutation ends with)."""
    prev = GENESIS
    for seq, order in enumerate(ledger["orders"], start=1):
        order.update(seq=seq, prev_sha256=prev)
        order["row_sha256"] = prev = digest(order)
    ledger["head"] = _head(ledger, prev)
    return ledger


def verify(ledger: Ledger) -> list[dict[str, str]]:
    """Offenders `{id, reason}` (bad_seq, bad_prev, bad_hash, and bad_head for the ledger anchor); empty is clean."""
    validate_shape(ledger)
    bad: list[dict[str, str]] = []
    prev = GENESIS
    for seq, order in enumerate(ledger.get("orders", []), start=1):
        oid = str(order.get("id", f"#{seq}"))
        for reason, ok in (
            ("bad_seq", order.get("seq") == seq),
            ("bad_prev", order.get("prev_sha256") == prev),
            ("bad_hash", digest(order) == order.get("row_sha256")),
        ):
            if not ok:
                bad.append({"id": oid, "reason": reason})
        prev = str(order.get("row_sha256"))
    if ledger.get("head") != _head(ledger, prev):  # a dropped tail, or edited ticks, leaves the chain itself clean
        bad.append({"id": "#ledger", "reason": "bad_head"})
    return bad


def validate_shape(ledger: Ledger) -> None:
    """Reject malformed typed counters and identities even when their integrity hashes were recomputed."""
    if type(ledger.get("schema")) is not int or ledger["schema"] != 1:
        raise ValueError("order_state_error")
    raw_ticks: object = ledger.get("ticked_loops")
    ticks = cast("list[Any]", raw_ticks)
    if not isinstance(raw_ticks, list):
        raise ValueError("order_state_error")
    if any(not isinstance(t, str) or not t.strip() for t in ticks):
        raise ValueError("order_state_error")
    head = ledger.get("head")
    if (
        len(ticks) != len(set(ticks))
        or not isinstance(head, dict)
        or type(cast("dict[str, Any]", head).get("count")) is not int
    ):
        raise ValueError("order_state_error")
    ids: set[str] = set()
    for order in ledger["orders"]:
        if not isinstance(order, dict) or not lifecycle.valid_record(cast("dict[str, Any]", order)):
            raise ValueError("order_state_error")
        order = cast("dict[str, Any]", order)
        oid, count, ev = order.get("id"), order.get("loops_since_recurrence"), order.get("evidence")
        if not isinstance(oid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,119}", oid) or oid in ids:
            raise ValueError("order_state_error")
        ids.add(oid)
        if type(count) is not int or count < 0 or order.get("status") not in ("active", "decayed"):
            raise ValueError("order_state_error")
        if any(not isinstance(order.get(k), str) or not order[k].strip() for k in ("created", "last_recurred")):
            raise ValueError("order_state_error")
        evidence = cast("list[Any]", ev)
        if not isinstance(ev, list) or not ev:
            raise ValueError("order_state_error")
        identities: set[tuple[str, str]] = set()
        for raw_e in evidence:
            if not isinstance(raw_e, dict):
                raise ValueError("order_state_error")
            e = cast("dict[str, Any]", raw_e)
            if any(not isinstance(e.get(k), str) or not e[k].strip() for k in ("session_id", "loop_id", "ts")):
                raise ValueError("order_state_error")
            ident = (e["session_id"], e["loop_id"])
            if ident in identities:
                raise ValueError("order_state_error")
            identities.add(ident)


def find(ledger: Ledger, order_id: str) -> dict[str, Any] | None:
    """The order with this id, or None."""
    return next((o for o in ledger["orders"] if o["id"] == order_id), None)


def _evidence(session_id: str, loop_id: str, ts: str) -> dict[str, str]:
    return {"session_id": session_id, "loop_id": loop_id, "ts": ts}


def record(
    ledger: Ledger,
    order_id: str,
    lesson: str,
    *,
    session_id: str,
    loop_id: str,
    now: str,
    scope: str = "repo",
    failure_mode: str | None = None,
) -> dict[str, Any]:
    """Add a new order or, on an id match, recur it. Returns {"ledger", "order", "created"}; the input is untouched."""
    new = copy.deepcopy(ledger)
    ev = _evidence(session_id, loop_id, now)
    order = find(new, order_id)
    if order is None:
        order = {
            "id": order_id,
            "created": now,
            "failure_mode": failure_mode or order_id,
            "lesson": lesson,
            "evidence": [ev],
            "last_recurred": now,
            "loops_since_recurrence": 0,
            "status": "active",
            "decayed_at": None,
            "scope": scope,
            "muninn": {"id": None, "state": "pending", "reason_code": "pending"},
        }
        new["orders"].append(order)
        created = True
    else:  # a recurrence revives a tombstone: the record is kept, only its status changes
        created = False
        lifecycle.require_identity(order, failure_mode, scope)
        if all((e["session_id"], e["loop_id"]) != (session_id, loop_id) for e in order["evidence"]):
            order.update(last_recurred=now, loops_since_recurrence=0, status="active", decayed_at=None)
            order["evidence"].append(ev)
        order["lesson"] = lesson
    return {"ledger": seal(new), "order": find(new, order_id), "created": created}


def tick(ledger: Ledger, loop_id: str, now: str, session_id: str | None = None) -> dict[str, Any]:
    """Count one loop: every active order this loop did not record gains 1 and decays at K. Idempotent per loop_id."""
    new = copy.deepcopy(ledger)
    decayed: list[str] = []
    identity = lifecycle.loop_key(session_id, loop_id) if session_id else loop_id
    if identity in new["ticked_loops"]:
        return {"ledger": new, "ticked": False, "decayed": decayed}
    new["ticked_loops"] = sorted([*new["ticked_loops"], identity])
    for order in new["orders"]:
        if order["status"] != "active" or any(
            e["loop_id"] == loop_id and (session_id is None or e["session_id"] == session_id) for e in order["evidence"]
        ):
            continue
        order["loops_since_recurrence"] += 1
        if order["loops_since_recurrence"] >= K:
            order.update(status="decayed", decayed_at=now)
            decayed.append(order["id"])
    return {"ledger": seal(new), "ticked": True, "decayed": decayed}


def set_muninn(ledger: Ledger, order_id: str, field: dict[str, Any]) -> Ledger:
    """A copy with the order's `muninn` field replaced (outside the hash, so the chain is unchanged)."""
    new = copy.deepcopy(ledger)
    order = find(new, order_id)
    if order is None:
        raise ValueError("order_not_found")
    order["muninn"] = dict(field)
    return new


def recurred(order: dict[str, Any]) -> bool:
    """Typed lifecycle test: the order recurred at least once after it was created."""
    return bool(order["last_recurred"] != order["created"])


def predicate(ledger: Ledger, retro_count: int) -> dict[str, Any]:
    """The graduation predicate: retro.json count >= 10, one recurred order, one decayed order."""
    orders = ledger["orders"]
    n_recurred = sum(1 for o in orders if recurred(o))
    n_decayed = sum(1 for o in orders if o["status"] == "decayed")
    met = retro_count >= RETRO_MIN and n_recurred >= 1 and n_decayed >= 1
    return {"met": met, "retro_count": retro_count, "recurred": n_recurred, "decayed": n_decayed}


def candidates(ledger: Ledger) -> list[dict[str, Any]]:
    """Active agnostic orders that recurred >= 2 times across >= 2 distinct session ids; citations join separately."""
    return [
        o
        for o in ledger["orders"]
        if o["scope"] == "agnostic"
        and o["status"] == "active"
        and len(o["evidence"]) - 1 >= 2
        and len({e["session_id"] for e in o["evidence"]}) >= 2
    ]


def view(ledger: Ledger, decayed: bool) -> str:
    """The generated Markdown view: decayed orders only (decayed=True) or active ones only."""
    want = "decayed" if decayed else "active"
    title = "Standing Orders (decayed tombstones)" if decayed else "Standing Orders"
    lines = [MARKER, f"# {title}", "", "Generated from orders.json; do not edit. Muninn holds the cited claim.", ""]
    for o in (x for x in ledger["orders"] if x["status"] == want):
        sessions = ", ".join(sorted({e["session_id"] for e in o["evidence"]}))
        lines += [
            f"## {o['id']}",
            f"- **loops_since_recurrence:** {o['loops_since_recurrence']}",
            f"- **created:** {o['created']}  **last_recurred:** {o['last_recurred']}  **scope:** {o['scope']}",
            f"- **muninn:** {o['muninn'].get('state')} {o['muninn'].get('id') or ''} {o['muninn'].get('reason_code')}",
            f"- **Failure mode:** {o['failure_mode']}",
            f"- **Lesson:** {' '.join(str(o['lesson']).split())}",
            f"- **Evidence:** {len(o['evidence'])} record(s); sessions {sessions}",
            "",
        ]
    return "\n".join(lines)


class LegacyParseError(ValueError):
    """A hand-written entry whose counter line is missing or not an integer; `.entry` names it."""

    def __init__(self, entry: str) -> None:
        """Remember the entry title."""
        super().__init__(entry)
        self.entry = entry


HEADING = re.compile(r"^#{2,3}\s+(?:Entry:\s*)?(.+?)\s*$")
COUNTER = re.compile(r"^-?\s*\*\*loops_since_recurrence:\*\*\s*(\S.*?)\s*$")
FIRST = re.compile(r"^-?\s*\*\*First (?:seen|observed):\*\*\s*(.*?)\s*$")
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def parse_legacy(text: str, now: str) -> list[dict[str, Any]]:
    """Parse the hand-written standing-orders.md into orders (unsealed, legacy_uncited); raises LegacyParseError."""
    blocks: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        head = HEADING.match(line)
        if head:
            if not head.group(1).strip():
                raise LegacyParseError("blank title")
            blocks.append((head.group(1), []))
        elif blocks:
            blocks[-1][1].append(line)
    if text.strip() and not blocks:
        raise LegacyParseError("no recognized entries")
    found: list[dict[str, Any]] = []
    for title, body in blocks:
        counters = [m.group(1) for m in map(COUNTER.match, body) if m]
        firsts = [m.group(1) for m in map(FIRST.match, body) if m]
        if len(counters) != 1 or not re.fullmatch(r"\d+", counters[0]) or len(firsts) != 1 or not firsts[0]:
            raise LegacyParseError(title)
        counter, first = counters[0], firsts[0]
        sid = SESSION_ID.search(first)
        rest = [x.strip() for x in body if x.strip() and not COUNTER.match(x) and not FIRST.match(x)]
        if not rest or any(o["id"] == slug(title) for o in found):
            raise LegacyParseError(title)
        found.append(
            {
                "id": slug(title),
                "created": now,
                "failure_mode": title,
                "lesson": "\n".join(rest),
                "evidence": [_evidence(sid.group(0) if sid else first or "legacy", "legacy-import", now)],
                "last_recurred": now,
                "loops_since_recurrence": int(counter),
                "status": "decayed" if int(counter) >= K else "active",
                "decayed_at": now if int(counter) >= K else None,
                "scope": "repo",
                "muninn": {"id": None, "state": "degraded", "reason_code": "legacy_uncited"},
                "legacy_first_seen": first,
                "legacy_text": "\n".join(body),
            }
        )
    return found


def load(path: Path) -> Ledger:
    """Read orders.json (an absent file is an empty ledger); raises ValueError on unreadable or non-ledger content."""
    if not path.exists():
        view = path.parent / "standing-orders.md"
        if view.is_file() and view.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0] == MARKER:
            raise ValueError("ledger_missing")  # a generated view exists, so the ledger was deleted
        return empty()
    try:
        loaded: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError("unreadable") from error
    ledger = cast("Ledger", loaded)
    if not isinstance(loaded, dict) or not isinstance(ledger.get("orders"), list):
        raise ValueError("not_a_ledger")
    ledger.setdefault("ticked_loops", [])
    return ledger


def save(path: Path, ledger: Ledger) -> None:
    """Atomic write (temp file in the same dir, then os.replace)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ledger, f, indent=1, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class ChainError(ValueError):
    """The ledger's hash chain is broken; `.offenders` names the orders."""

    def __init__(self, offenders: list[dict[str, str]]) -> None:
        """Remember the offenders."""
        super().__init__("order_chain_broken")
        self.offenders = offenders


def open_ledger(repo_dir: Path) -> Ledger:
    """Load + verify the repo-key dir's orders.json; raises ChainError or ValueError (unreadable)."""
    ledger = load(repo_dir / "orders.json")
    bad = verify(ledger)
    if bad:
        raise ChainError(bad)
    return ledger


def retro_count(repo_dir: Path) -> int:
    """Distinct logical loops with valid completed, owner/source-bound retrospectives."""
    return lifecycle.retro_count(repo_dir)


def trace(command: str, outcome: str, reason: str, session_id: str, loop_id: str | None = None) -> None:
    """Fail-open trace row via hooks/scripts/lib/trace_row.py of this layout."""
    try:
        path = Path(__file__).resolve().parents[2] / "hooks/scripts/lib/trace_row.py"
        runpy.run_path(str(path))["append_row"](command, outcome, reason, session_id or NO_SESSION, loop_id, None)
    except Exception:  # noqa: BLE001  fail open: tracing never blocks the ledger
        return
