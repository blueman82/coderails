"""teardown.jsonl: the append-only record of which Phase 13 teardown steps really ran (provider-neutral).

A sibling of progress.json, deliberately: it needs no progress.json lock and no graph code. One row per step,
`{step, ts, session_id, loop_id, evidence_sha256}`, written with a single O_APPEND write. `proof.py run --all`,
`orders.py prepare`, `decision_record.flush_pending` and `retro.py assemble` each record their own step; `orders.py`
`tick` records the post-completion apply observation. A step whose
latest row carries the same evidence is not appended twice, so a repeat run is idempotent. Cooperating-agent safeguard:
a same-user agent can append a row by hand; the rows prove the commands ran only as far as the evidence hash they
carry, which `retro.py assemble` binds into the retro.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
import runpy
from pathlib import Path
from typing import Any, cast

NAME = "teardown.jsonl"
STEPS = (
    "proof_run",
    "decisions_flushed",
    "orders_prepared",
    "retro_assembled",
    "orders_ticked",
    "orders_rendered",
    "lessons_written",
)
REQUIRED = STEPS[:4]  # orders_ticked is a post-completion apply observation; lessons_written is optional


def normalize_consumed_complete_stop(state: dict[str, Any]) -> None:
    """Undo only the final same-revision complete Stop hook consumption for D4 source checks."""
    if state.get("status") != "complete":
        return
    stops: object = state.get("stops")
    if (
        not isinstance(stops, list)
        or not stops
        or not all(isinstance(row, dict) for row in cast("list[object]", stops))
    ):
        return
    last = cast("dict[str, Any]", stops[-1])
    previous = cast("list[dict[str, Any]]", stops[:-1])
    if (
        set(last) != {"seq", "category", "reason_code", "reason", "revision", "consumed", "at"}
        or last.get("category") != "complete"
        or last.get("consumed") is not True
        or type(last.get("revision")) is not int
        or last["revision"] != state.get("revision")
        or type(last.get("seq")) is not int
        or any(type(row.get("seq")) is not int for row in previous)
        or last["seq"] != max((row["seq"] for row in previous), default=0) + 1
        or not isinstance(last.get("reason_code"), str)
        or not last["reason_code"].strip()
        or not isinstance(last.get("reason"), str)
        or not last["reason"].strip()
        or type(last.get("at")) not in (int, float)
        or not math.isfinite(last["at"])
    ):
        return
    last["consumed"] = False


def as_list(value: object) -> list[Any]:
    """Return value as a list, or [] when it is not one (a hand-edited state never raises here)."""
    return list(value) if isinstance(value, list) else []  # pyright: ignore[reportUnknownArgumentType]


def sha_json(value: object) -> str:
    """sha256 of the canonical JSON of value."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha(path: Path) -> str | None:
    """sha256 of the file bytes, or None when the file is absent."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_rows(state_dir: Path) -> list[dict[str, Any]]:
    """Every parsed row; ValueError('teardown_unreadable') for a torn line or a row naming an unknown step."""
    try:
        lines = (state_dir / NAME).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except OSError as error:
        raise ValueError("teardown_unreadable") from error
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value: object = json.loads(line)
        except ValueError as error:
            raise ValueError("teardown_unreadable") from error
        if not isinstance(value, dict) or cast("dict[str, Any]", value).get("step") not in STEPS:
            raise ValueError("teardown_unreadable")
        rows.append(cast("dict[str, Any]", value))
    return rows


def steps_done(rows: list[dict[str, Any]]) -> list[str]:
    """Step names ordered by their latest receipt so a refreshed preparation can supersede stale history."""
    latest: dict[str, int] = {}
    for index, row in enumerate(rows):
        latest[row["step"]] = index
    return sorted(latest, key=latest.__getitem__)


def hashed_view(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows the retro binds; post-completion apply observations may land after assembly."""
    return [r for r in rows if r["step"] in REQUIRED]


def order_problem(done: list[str]) -> str:
    """'' when the required steps are all present in canonical order, else a short description."""
    missing = [s for s in REQUIRED if s not in done]
    if missing:
        return "missing " + ", ".join(missing)
    positions = [done.index(s) for s in REQUIRED]
    if positions != sorted(positions):
        return "out of order (expected " + " < ".join(REQUIRED) + "; got " + " < ".join(done) + ")"
    return ""


def _trace(step: str, session_id: str, loop_id: str | None) -> None:
    """Fail-open trace row `teardown.step` (hooks/scripts/lib/trace_row.py of this layout)."""
    try:
        path = Path(__file__).resolve().parents[2] / "hooks/scripts/lib/trace_row.py"
        runpy.run_path(str(path))["append_row"](
            "teardown.step", "recorded", "ok", session_id or "teardown-nosession", loop_id, {"step": step}
        )
    except Exception:  # noqa: BLE001  fail open: tracing never blocks teardown
        return


def record(state_dir: Path, step: str, session_id: str, loop_id: str | None, evidence_sha256: str | None) -> bool:
    """Append one row unless its matching receipt is current; never raises."""
    if step not in STEPS or not (state_dir / "progress.json").is_file():
        return False
    try:
        if loop_id is None:
            loaded: object = json.loads((state_dir / "progress.json").read_text(encoding="utf-8"))
            loop_id = str(cast("dict[str, Any]", loaded).get("loop_id")) if isinstance(loaded, dict) else None
        rows = read_rows(state_dir)
        latest = [r for r in rows if r["step"] == step]
        if latest and latest[-1].get("evidence_sha256") == evidence_sha256:
            proof_after_flush = step == "decisions_flushed" and max(
                (i for i, row in enumerate(rows) if row["step"] == "proof_run"), default=-1
            ) > max((i for i, row in enumerate(rows) if row["step"] == "decisions_flushed"), default=-1)
            if not proof_after_flush:
                return False
        row = {
            "step": step,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "loop_id": loop_id,
            "evidence_sha256": evidence_sha256,
        }
        descriptor = os.open(str(state_dir / NAME), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        return False
    _trace(step, session_id, loop_id)
    return True
