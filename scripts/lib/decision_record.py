#!/usr/bin/env python3
"""Write hash-chained loop decisions and sync them to Muninn for either provider.

Each row keeps phase and decision for the dashboard. Its hash covers all fields except
the hash itself and `muninn`. A prior hash links the rows. `verify_chain` finds edits,
missing middle rows, and changed order. A same-user agent can rewrite the whole chain
or remove its last row. It can also set `muninn.state` to `written`; verify a claimed
Muninn id with `list_records`. This check does not authenticate the writer.

Both graph CLIs call `record` with a provider transition function. The function first
writes a `syncing` row under the graph lock. It calls Muninn outside that lock, then
writes the result under the lock. Exit code 0 means written or disabled; 3 means
degraded or unknown; 2 means refused. `flush_pending` retries pending and safe
degraded rows. An ambiguous result stays `syncing` or `unknown` until it is resolved.
A citation needs a user prompt or quote. Short approval text can degrade the sync.
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
from typing import Any, Optional, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import teardown_steps  # noqa: E402

GENESIS = "0" * 64
HASH_EXCLUDED = ("row_sha256", "muninn")
QUOTE_MIN, QUOTE_MAX, CLAIM_MAX = 12, 300, 500  # muninn's quote and claim length rules
REFUSALS = ("wrong_session", "wrong_loop", "wrong_revision", "blank_phase", "blank_decision", "invalid_chain")
Transition = Callable[[Path, Callable[[dict[str, Any]], dict[str, Any]]], dict[str, Any]]
StatusResolver = Callable[[dict[str, Any], Optional[int], Optional[str], bool, int], None]


def _collapse(text: str) -> str:
    return " ".join(text.split())


def row_digest(row: dict[str, Any]) -> str:
    """sha256 over the canonical JSON of the row minus `muninn` and `row_sha256`."""
    body = {k: v for k, v in row.items() if k not in HASH_EXCLUDED}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _rows(state: dict[str, Any]) -> list[Any]:
    value: Any = state.get("decisions_absorbed")
    if "decisions_absorbed" in state and not isinstance(value, list):
        raise ValueError("invalid_chain")
    return list(value) if isinstance(value, list) else []  # pyright: ignore[reportUnknownArgumentType]


def _as_row(value: Any) -> dict[str, Any]:  # noqa: ANN401
    """A decision row as a dict; anything else (a hand-written string, null) is an empty row."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def add_decision(
    state: dict[str, Any],
    session: str,
    phase: str,
    decision: str,
    expected_loop_id: str,
    expected_revision: int,
    flip_condition: str | None = None,
    unit: str | None = None,
    now: datetime.datetime | str | None = None,
    chosen: str | None = None,
    worker_status_seq: int | None = None,
    human_answer: bool = False,
    status_resolver: StatusResolver | None = None,
) -> dict[str, Any]:
    """Append one hashed row; return {"state", "decision"}. Raises ValueError(<REFUSALS code>) and mutates nothing."""
    if state.get("session_id") != session:
        raise ValueError("wrong_session")
    if state.get("loop_id") != expected_loop_id:
        raise ValueError("wrong_loop")
    if state.get("revision") != expected_revision:
        raise ValueError("wrong_revision")
    if not str(phase or "").strip():
        raise ValueError("blank_phase")
    if not str(decision or "").strip():
        raise ValueError("blank_decision")
    if chosen is not None and not chosen.strip():
        raise ValueError("record_decision_refused_field")
    if worker_status_seq is not None and (chosen is None or status_resolver is None):
        raise ValueError("record_decision_refused_field")
    stamp = now.isoformat(timespec="seconds") if isinstance(now, datetime.datetime) else now
    rows = _rows(state)
    ensure_chain(state)
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
    if chosen is not None:
        row["chosen"] = chosen.strip()
    if worker_status_seq is not None:
        row["worker_status_seq"] = worker_status_seq
    row["row_sha256"] = row_digest(row)
    row["muninn"] = {"state": "syncing"}
    new = copy.deepcopy(state)
    if status_resolver is not None:
        status_resolver(new, worker_status_seq, chosen, human_answer, row["seq"])
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


def ensure_chain(state: dict[str, Any]) -> None:
    """Refuse a damaged decision chain before another local or external write."""
    marker = state.get("chain_started_seq")
    if marker is not None and (type(marker) is not int or marker < 1):
        raise ValueError("invalid_chain")
    if verify_chain(_rows(state), marker):
        raise ValueError("invalid_chain")


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
    refused = ma.resolve_cite(rec, False, session_id)
    res: ma.Degraded | ma.Written = refused or ma.add(rec, session_id)
    field: dict[str, Any]
    if isinstance(res, ma.Written):
        field = {"state": "written", "id": res.id, "reason_code": "ok"}
    else:
        off = res.reason == "memory_backend_off"
        uncertain = refused is None and res.reason in {"muninn_error", "muninn_timeout", "muninn_bad_output"}
        field = {
            "state": "disabled" if off else "unknown" if uncertain else "degraded",
            "id": None,
            "reason_code": res.reason,
        }
    _trace("decision.sync", field["state"], field["reason_code"], session_id, loop_id)
    return field


def _owned_row(state: dict[str, Any], session: str, loop_id: str, row_sha256: str) -> dict[str, Any]:
    if state.get("session_id") != session or state.get("loop_id") != loop_id:
        raise ValueError("sync_unavailable")
    for row in map(_as_row, _rows(state)):
        if row.get("row_sha256") == row_sha256:
            return row
    raise ValueError("sync_unavailable")


def mark_synced(
    state: dict[str, Any], session: str, loop_id: str, row_sha256: str, field: dict[str, Any]
) -> dict[str, Any]:
    """Patch only the row owned by the original session and loop under the graph lock."""
    ensure_chain(state)
    new = copy.deepcopy(state)
    row = _owned_row(new, session, loop_id, row_sha256)
    if _as_row(row.get("muninn")).get("state") != "syncing":
        raise ValueError("sync_unavailable")
    row["muninn"] = dict(field)
    return new


def _exit_code(field: dict[str, Any]) -> int:
    return 0 if field["state"] in {"written", "disabled"} else 3


def claim_sync(state: dict[str, Any], session: str, loop_id: str, row_sha256: str) -> dict[str, Any]:
    """Claim a retry under the graph lock before contacting Muninn."""
    ensure_chain(state)
    new = copy.deepcopy(state)
    row = _owned_row(new, session, loop_id, row_sha256)
    if _as_row(row.get("muninn")).get("state") not in {"pending", "degraded"}:
        raise ValueError("sync_unavailable")
    row["muninn"] = {"state": "syncing", "id": None, "reason_code": "sync_in_flight"}
    return new


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
        return {"state": "unknown", "id": None, "reason_code": "muninn_error"}


def record(
    path: Path,
    session: str,
    phase: str,
    decision: str,
    *,
    expected_loop_id: str,
    expected_revision: int,
    transition: Transition,
    flip_condition: str | None = None,
    unit: str | None = None,
    prompt_raw: str | None = None,
    cite_quote: str | None = None,
    now: datetime.datetime | str | None = None,
    chosen: str | None = None,
    worker_status_seq: int | None = None,
    human_answer: bool = False,
    status_resolver: StatusResolver | None = None,
) -> dict[str, Any]:
    """Append locally, sync to Muninn outside the lock, patch the row. Returns {recorded, seq, muninn, exit_code}."""
    held: dict[str, Any] = {}

    def append(state: dict[str, Any]) -> dict[str, Any]:
        out = add_decision(
            state,
            session,
            phase,
            decision,
            expected_loop_id,
            expected_revision,
            flip_condition,
            unit,
            now,
            chosen,
            worker_status_seq,
            human_answer,
            status_resolver,
        )
        held.update(out["decision"])
        new: dict[str, Any] = out["state"]
        return new

    try:
        state = transition(path, append)
    except ValueError as error:
        message = str(error)
        marked = re.search(r"\[reason_code=(record_decision_refused_[a-z_]+)\]", message)
        raw = str(getattr(error, "code", marked.group(1) if marked else message))
        code = raw if raw in REFUSALS or raw.startswith("record_decision_refused_") else "state_error"
        reason = code if code.startswith("record_decision_refused_") else f"decision_{code}"
        _trace("decision.record", "refused", reason, session, None)
        return {"recorded": False, "reason_code": reason, "exit_code": 2}
    _trace("decision.record", "recorded", "ok", session, str(state.get("loop_id")))
    field = _sync_safely(held, state, session, prompt_raw, cite_quote)
    seq = held["seq"]
    try:
        transition(
            path,
            partial(
                mark_synced,
                session=session,
                loop_id=str(state.get("loop_id")),
                row_sha256=held["row_sha256"],
                field=field,
            ),
        )
    except ValueError:
        _trace("decision.record", "degraded", "decision_sync_unknown", session, str(state.get("loop_id")))
        return {"recorded": True, "seq": seq, "muninn": field, "reason_code": "decision_sync_unknown", "exit_code": 3}
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
    refused: dict[str, Any] = {}

    def checked(state: dict[str, Any]) -> dict[str, Any]:
        # Provider transitions may stamp even an identity transform. Reject before that write.
        if state.get("session_id") != session:
            refused.update(reason="decision_wrong_session", loop_id=None)
            raise ValueError("wrong_session")
        try:
            ensure_chain(state)
        except ValueError:
            refused.update(reason="decision_invalid_chain", loop_id=str(state.get("loop_id")))
            raise
        return state

    try:
        state = transition(path, checked)
    except ValueError:
        if not refused:
            raise
        reason = refused["reason"]
        _trace("decision.flush", "refused", reason, session, refused["loop_id"])
        return {"synced": [], "reason_code": reason, "exit_code": 2}
    if any(_as_row(row.get("muninn")).get("state") in {"syncing", "unknown"} for row in map(_as_row, _rows(state))):
        _trace("decision.flush", "degraded", "decision_sync_unknown", session, str(state.get("loop_id")))
        return {"synced": [], "reason_code": "decision_sync_unknown", "exit_code": 3}
    synced: list[dict[str, Any]] = []
    for row in map(_as_row, _rows(state)):
        if not row.get("row_sha256") or not isinstance(row.get("seq"), int):
            continue  # legacy or hand-written row: not ours to sync
        if _as_row(row.get("muninn")).get("state", "pending") not in ("pending", "degraded"):
            continue
        try:
            transition(
                path,
                partial(claim_sync, session=session, loop_id=str(state.get("loop_id")), row_sha256=row["row_sha256"]),
            )
        except ValueError:
            _trace("decision.flush", "degraded", "decision_sync_unknown", session, str(state.get("loop_id")))
            return {"synced": synced, "reason_code": "decision_sync_unknown", "exit_code": 3}
        field = _sync_safely(row, state, session, prompt_raw, cite_quote)
        try:
            transition(
                path,
                partial(
                    mark_synced,
                    session=session,
                    loop_id=str(state.get("loop_id")),
                    row_sha256=row["row_sha256"],
                    field=field,
                ),
            )
        except ValueError:
            _trace("decision.flush", "degraded", "decision_sync_unknown", session, str(state.get("loop_id")))
            return {"synced": synced, "reason_code": "decision_sync_unknown", "exit_code": 3}
        synced.append({"seq": row["seq"], "muninn": field})
    final = transition(path, lambda s: s)  # evidence = the rows as they stand after the retries
    teardown_steps.record(
        path.parent,
        "decisions_flushed",
        session,
        final.get("loop_id"),
        teardown_steps.sha_json(final.get("decisions_absorbed")),
    )
    return {"synced": synced, "exit_code": 3 if any(_exit_code(x["muninn"]) == 3 for x in synced) else 0}
