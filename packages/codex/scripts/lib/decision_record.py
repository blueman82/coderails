#!/usr/bin/env python3
"""Typed, hash-chained loop decisions: the only writer of `decisions_absorbed`, synced to Muninn (provider-neutral).

A decision row is `{seq, phase, decision, flip_condition, unit, revision, ts, prev_sha256, row_sha256, muninn}`; the
dashboard's `{phase, decision}` keys are unchanged. `row_sha256` covers every field except `muninn` and itself, and
`prev_sha256` names the previous row's hash (64 zeros for the first hashed row), so an edited, dropped, swapped or
unhashed row is named by `verify_chain`. Cooperating-agent safeguard: a same-user agent can rewrite the file and
recompute the whole chain; this is tamper-evidence, not a security boundary, and dropping the LAST row is undetectable.
The `muninn` field is OUTSIDE the hash: a same-user agent can set `{state: written}` by hand and `flush_pending`
will not retry it, so "synced to Muninn" is unauthenticated here; check the id against Muninn `list_records`.

Entry point for lane A (`graph.py record-decision`), `transition(path, fn)` being the provider's lock wrapper
(Claude `hooks.scripts.lib.graph_executor.transition`; Codex `graph_io.locked/load/write` wrapped to the same shape):

    out = record(path, session, phase, decision, transition=transition, flip_condition=fc, unit=unit)
    print(json.dumps(out))
    return out["exit_code"]

`record` appends the local row first under the lock (the authoritative loop record is never lost), calls Muninn outside
the lock, then patches the row's `muninn` field under the lock again. exit_code: 0 written or disabled, 3 degraded
(reason code printed, trace row decision.sync/degraded/<code>, local row kept), 2 refused (nothing written).
`flush_pending` retries rows left pending or degraded at teardown. Muninn refuses an approval-only citation and an
agent cannot cite itself, so the cite is a quote of `authorising_prompt_raw` unless the caller passes a substantive
user `cite_quote`; a short prompt such as "yes" stays a visible degrade. Never falls back to Markdown.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import runpy
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import memory_adapter as ma  # noqa: E402

GENESIS = "0" * 64
HASH_EXCLUDED = ("row_sha256", "muninn")
QUOTE_MIN, QUOTE_MAX, CLAIM_MAX = 12, 300, 500  # muninn's quote and claim length rules
REFUSALS = ("wrong_session", "blank_phase", "blank_decision")
Transition = Callable[[Path, Callable[[dict[str, Any]], dict[str, Any]]], dict[str, Any]]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def row_digest(row: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the row minus `muninn` and `row_sha256`."""
    body = {k: v for k, v in row.items() if k not in HASH_EXCLUDED}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _rows(state: dict[str, Any]) -> list[Any]:
    value: Any = state.get("decisions_absorbed")
    rows: list[Any] = list(value) if isinstance(value, list) else []  # pyright: ignore[reportUnknownArgumentType]
    return rows


def _as_row(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """A decision row as a dict; anything else (a hand-written string, null) is an empty row."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def add_decision(
    state: dict[str, Any],
    session: str,
    phase: str,
    decision: str,
    flip_condition: str | None = None,
    unit: str | None = None,
    now: datetime.datetime | str | None = None,
) -> dict[str, Any]:
    """Append one hashed row; return {"state", "decision"}. Raises ValueError(<REFUSALS code>) and mutates nothing."""
    if state.get("session_id") != session:
        raise ValueError("wrong_session")
    if not str(phase or "").strip():
        raise ValueError("blank_phase")
    if not str(decision or "").strip():
        raise ValueError("blank_decision")
    stamp = now.isoformat(timespec="seconds") if isinstance(now, datetime.datetime) else now
    rows = _rows(state)
    last = _as_row(rows[-1]) if rows else {}
    row: dict[str, Any] = {
        "seq": len(rows) + 1,
        "phase": phase,
        "decision": decision,
        "flip_condition": flip_condition,
        "unit": unit,
        "revision": state.get("revision"),
        "ts": stamp or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "prev_sha256": last.get("row_sha256") or GENESIS,
    }
    row["row_sha256"] = row_digest(row)
    row["muninn"] = {"state": "pending"}
    new = copy.deepcopy(state)
    new["decisions_absorbed"] = [*rows, row]
    new.setdefault("chain_started_seq", row["seq"])  # first hashed row of this loop; see verify_chain
    return {"state": new, "decision": row}


def verify_chain(rows: list[Any], chain_start: int | None = None) -> list[dict[str, Any]]:
    """Return offenders `{seq, reason}`; empty means clean. Rows before the first hashed row are legacy and ignored.

    Pass the state's `chain_started_seq` as `chain_start` so unhashed rows at or after it are offenders even when every
    hash was stripped; without it an all-unhashed list verifies clean (the marker lives in the same file, so a
    same-user agent that also deletes it is the documented boundary).
    """
    bad: list[dict[str, Any]] = []
    hashed = False
    prev = GENESIS
    for index, item in enumerate(rows, start=1):
        row = _as_row(item)
        if not row.get("row_sha256"):
            if hashed or (chain_start is not None and index >= chain_start):
                bad.append({"seq": index, "reason": "unhashed_row"})
            prev = GENESIS
            continue
        hashed = True
        if row.get("seq") != index:
            bad.append({"seq": row.get("seq", index), "reason": "bad_seq"})
        if row.get("prev_sha256") != prev:
            bad.append({"seq": row.get("seq", index), "reason": "bad_prev"})
        if row_digest(row) != row["row_sha256"]:
            bad.append({"seq": row.get("seq", index), "reason": "bad_hash"})
        prev = str(row["row_sha256"])
    return bad


def pick_quote(prompt_raw: str) -> str:
    """The first line, else first sentence, of 12-300 chars from the prompt (whitespace-collapsed, still verbatim)."""
    lines = [_collapse(x) for x in prompt_raw.splitlines() if x.strip()]
    sentences = re.split(r"(?<=[.!?])\s+", _collapse(prompt_raw))
    for cand in (*lines, *sentences):
        if QUOTE_MIN <= len(cand) <= QUOTE_MAX:
            return cand
    return _collapse(prompt_raw)[:QUOTE_MAX]


def _trace(command: str, outcome: str, reason: str, session: str, loop_id: str | None) -> None:
    """Fail-open trace row (hooks/scripts/lib/trace_row.py of this layout)."""
    try:
        path = Path(__file__).resolve().parents[2] / "hooks/scripts/lib/trace_row.py"
        runpy.run_path(str(path))["append_row"](command, outcome, reason, session, loop_id, None)
    except Exception:  # fail open: tracing never blocks the record
        return


def sync_row(
    row: dict[str, Any], loop_id: str, session_id: str, prompt_raw: str, cite_quote: str | None = None
) -> dict[str, Any]:
    """Write one decision to Muninn; return the muninn field {state: written|degraded|disabled, id, reason_code}."""
    quote = _collapse(cite_quote) if cite_quote and cite_quote.strip() else pick_quote(prompt_raw or "")
    tag = "run-" + re.sub(r"[^a-z0-9_-]", "-", loop_id.lower())[:28]
    claim = _collapse(f"{row['phase']}: {row['decision']}")
    rec = ma.Record("loop", "decision", claim[:CLAIM_MAX], "", quote, [tag], loop_id, "inferred")
    res: ma.Degraded | ma.Written = ma.resolve_cite(rec, False, session_id) or ma.add(rec, session_id)
    field: dict[str, Any]
    if isinstance(res, ma.Written):
        field = {"state": "written", "id": res.id, "reason_code": "ok"}
    else:
        off = res.reason == "memory_backend_off"
        field = {"state": "disabled" if off else "degraded", "id": None, "reason_code": res.reason}
    _trace("decision.sync", field["state"], field["reason_code"], session_id, loop_id)
    return field


def mark_synced(state: dict[str, Any], seq: int, field: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of state with row `seq`'s muninn field replaced; ValueError when no such row."""
    new = copy.deepcopy(state)
    for row in map(_as_row, _rows(new)):
        if row.get("seq") == seq:
            row["muninn"] = dict(field)
            return new
    raise ValueError("no_such_seq")


def _exit_code(field: dict[str, Any]) -> int:
    return 3 if field["state"] == "degraded" else 0


def _sync_safely(
    row: dict[str, Any], state: dict[str, Any], session: str, prompt: str | None, cite: str | None
) -> dict[str, Any]:
    """sync_row that can never raise: a crash is a muninn_error degrade, the local row is already safe."""
    loop_id = str(state.get("loop_id"))
    raw = state.get("authorising_prompt_raw") if prompt is None else prompt
    try:
        return sync_row(row, loop_id, session, str(raw or ""), cite)
    except Exception:  # noqa: BLE001
        _trace("decision.sync", "degraded", "muninn_error", session, loop_id)
        return {"state": "degraded", "id": None, "reason_code": "muninn_error"}


def record(
    path: Path,
    session: str,
    phase: str,
    decision: str,
    *,
    transition: Transition,
    flip_condition: str | None = None,
    unit: str | None = None,
    prompt_raw: str | None = None,
    cite_quote: str | None = None,
    now: datetime.datetime | str | None = None,
) -> dict[str, Any]:
    """Append locally, sync to Muninn outside the lock, patch the row. Returns {recorded, seq, muninn, exit_code}."""
    held: dict[str, Any] = {}

    def append(state: dict[str, Any]) -> dict[str, Any]:
        out = add_decision(state, session, phase, decision, flip_condition, unit, now)
        held.update(out["decision"])
        new: dict[str, Any] = out["state"]
        return new

    try:
        state = transition(path, append)
    except ValueError as error:
        code = str(error) if str(error) in REFUSALS else "state_error"
        _trace("decision.record", "refused", f"decision_{code}", session, None)
        return {"recorded": False, "reason_code": f"decision_{code}", "exit_code": 2}
    _trace("decision.record", "recorded", "ok", session, str(state.get("loop_id")))
    field = _sync_safely(held, state, session, prompt_raw, cite_quote)
    seq = held["seq"]
    transition(path, lambda s: mark_synced(s, seq, field))
    return {"recorded": True, "seq": seq, "muninn": field, "exit_code": _exit_code(field)}


def flush_pending(
    path: Path,
    session: str,
    *,
    transition: Transition,
    prompt_raw: str | None = None,
    cite_quote: str | None = None,
) -> dict[str, Any]:
    """Retry every row still pending or degraded (teardown). Returns {synced: [{seq, muninn}], exit_code}."""
    state = transition(path, lambda s: s)  # identity transition: a read under the provider's lock
    if state.get("session_id") != session:
        _trace("decision.flush", "refused", "decision_wrong_session", session, None)
        return {"synced": [], "reason_code": "decision_wrong_session", "exit_code": 2}
    synced: list[dict[str, Any]] = []
    for row in map(_as_row, _rows(state)):
        if not row.get("row_sha256") or not isinstance(row.get("seq"), int):
            continue  # legacy or hand-written row: not ours to sync
        if _as_row(row.get("muninn")).get("state", "pending") not in ("pending", "degraded"):
            continue
        field = _sync_safely(row, state, session, prompt_raw, cite_quote)
        transition(path, partial(mark_synced, seq=row["seq"], field=field))
        synced.append({"seq": row["seq"], "muninn": field})
    return {"synced": synced, "exit_code": 3 if any(x["muninn"]["state"] == "degraded" for x in synced) else 0}
