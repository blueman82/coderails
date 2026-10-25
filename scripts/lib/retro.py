#!/usr/bin/env python3
"""Assemble retro.json (schema_version 3) from the loop's own artifacts, with source hashes (provider-neutral).

    retro.py assemble <state-dir> --session S [--free-file F]

<state-dir> holds progress.json, evals.json, proof.json, proof_results.jsonl and teardown.jsonl. The retro copies
`decisions_absorbed`, `loop_stop_counts` and the envelope verbatim from progress.json, summarises evals and proof
results, mines cost (`loop_cost.py`, fail-open) and hook blocks (Claude layout only), reads `teardown.steps_done` from
teardown.jsonl, adds a `memory` degrade section from trace rows, and binds all of it with `source_hashes`
(see retro_check.py, the gate that recomputes them). Free-form notes (artifacts with their verifying check, review
themes, raw notes) come in with --free-file and live under `free`, which is NOT hashed. Before assembling,
`decision_record.flush_pending` retries decisions that never reached Muninn.

Exit 0 assembled, 2 refused (reason_code printed, nothing written), 3 assembled but Muninn degraded (retro written,
degraded[] printed with reason codes). Never falls back to Markdown.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import importlib
import io
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # plugin root, so `scripts.lib` resolves as a script
from scripts.lib import decision_record, retro_check, teardown_steps  # noqa: E402

TRACED = ("decision.sync", "order.record", "order.cite")


def _load(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise ValueError(f"{path.name} is unreadable") from error
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def provider_transition() -> decision_record.Transition:
    """The lock wrapper of the provider this file is installed in (Claude executor, else the Codex graph_io)."""
    if (ROOT / "hooks/scripts/lib/graph_executor.py").is_file():
        claude: Any = importlib.import_module("hooks.scripts.lib.graph_executor")
        return cast("decision_record.Transition", claude.transition)
    sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
    graph_io: Any = importlib.import_module("graph_io")

    def codex(path: Path, fn: Any) -> dict[str, Any]:  # noqa: ANN401
        with graph_io.locked(path):
            new = fn(graph_io.load(path))
            graph_io.write(path, new)
            return cast("dict[str, Any]", new)

    return codex


def _mine(module: str, function: str, session: str) -> Any:  # noqa: ANN401
    """Call hooks.scripts.lib.<module>.<function>(session) when this layout ships it; stderr noise is dropped."""
    try:
        mod = __import__(f"hooks.scripts.lib.{module}", fromlist=[function])
        with contextlib.redirect_stderr(io.StringIO()):
            return getattr(mod, function)(session)
    except Exception:  # noqa: BLE001  fail open: a missing or failing miner leaves the field empty
        return {}


def memory_section(session: str, loop_id: str | None) -> dict[str, Any]:
    """Degraded typed-record trace rows of this session, counted by command and reason code."""
    degraded: dict[str, dict[str, int]] = {}
    lines: list[str] = []
    try:
        path: Path | None = runpy.run_path(str(ROOT / "hooks/scripts/lib/trace_row.py"))["trace_path"](session)
        lines = path.read_text(encoding="utf-8").splitlines() if path else []
    except Exception:  # noqa: BLE001  fail open: no trace file means no degrade rows to count
        lines = []
    for line in lines:
        try:
            loaded: object = json.loads(line)
        except ValueError:
            continue
        row = cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else {}
        ours = row.get("command") in TRACED and row.get("outcome") == "degraded"
        if ours and (loop_id is None or row.get("loop_id") in (None, loop_id)):
            bucket = degraded.setdefault(str(row["command"]), {})
            code = str(row.get("reason_code"))
            bucket[code] = bucket.get(code, 0) + 1
    return {"degraded": {k: dict(sorted(v.items())) for k, v in sorted(degraded.items())}}


def _flush(state_dir: Path, state: dict[str, Any], session: str) -> dict[str, Any]:
    """Retry decisions that never reached Muninn, then make sure the step is recorded."""
    rows = teardown_steps.read_rows(state_dir)
    if any(row.get("step") == "orders_prepared" for row in rows):
        decisions = [
            cast("dict[str, Any]", item)
            for item in teardown_steps.as_list(state.get("decisions_absorbed"))
            if isinstance(item, dict)
        ]
        if any(
            isinstance(row.get("muninn"), dict) and row["muninn"].get("state") in {"syncing", "unknown"}
            for row in decisions
        ):
            return {"synced": [], "reason_code": "decision_sync_unknown", "exit_code": 3}
        latest_flush = next((row for row in reversed(rows) if row.get("step") == "decisions_flushed"), None)
        if latest_flush is None or latest_flush.get("evidence_sha256") != teardown_steps.sha_json(
            state.get("decisions_absorbed")
        ):
            return {"synced": [], "reason_code": "decisions_not_flushed", "exit_code": 2}
        degraded = [
            {"seq": row["seq"], "muninn": row["muninn"]}
            for row in decisions
            if isinstance(row.get("muninn"), dict) and row["muninn"].get("state") == "degraded"
        ]
        return {"synced": degraded, "exit_code": 3 if degraded else 0}
    value: object = state.get("decisions_absorbed")
    todo = 0
    for item in teardown_steps.as_list(value):
        row = cast("dict[str, Any]", item) if isinstance(item, dict) else {}
        field: object = row.get("muninn") or {}
        pending = cast("dict[str, Any]", field).get("state", "pending") in ("pending", "degraded", "syncing", "unknown")
        todo += bool(row.get("row_sha256")) and pending
    if todo:
        return decision_record.flush_pending(state_dir / "progress.json", session, transition=provider_transition())
    evidence = teardown_steps.sha_json(state.get("decisions_absorbed"))
    positions = {row["step"]: index for index, row in enumerate(rows)}
    latest_flush = next((row for row in reversed(rows) if row.get("step") == "decisions_flushed"), None)
    proof_ran_after_flush = positions.get("proof_run", -1) > positions.get("decisions_flushed", -1)
    if latest_flush is None or latest_flush.get("evidence_sha256") != evidence or proof_ran_after_flush:
        teardown_steps.record(state_dir, "decisions_flushed", session, state.get("loop_id"), evidence)
    return {"synced": [], "exit_code": 0}


def assemble(state_dir: Path, session: str, free: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    """Write <state-dir>/retro.json; return ({retro, degraded[], missing_steps}, exit code)."""
    try:
        state = _load(state_dir / "progress.json")
    except ValueError:
        return {"reason_code": "retro_state_error"}, 2
    if not state or state.get("session_id") != session:
        return {"reason_code": "retro_wrong_session"}, 2
    flushed = _flush(state_dir, state, session)
    if flushed.get("exit_code") == 2:
        return {"reason_code": flushed.get("reason_code", "retro_state_error")}, 2
    if flushed.get("reason_code") == "decision_sync_unknown":
        return {"reason_code": "decision_sync_unknown"}, 3
    state = _load(state_dir / "progress.json")
    loop_id = state.get("loop_id")
    pre = retro_check.retro_step_hashes(state, state_dir)
    teardown_steps.record(state_dir, "retro_assembled", session, loop_id, teardown_steps.sha_json(pre))
    hashes = retro_check.source_hashes(state, state_dir)
    cost: Any = _mine("loop_cost", "mine_token_usage", session)
    cost = cast("dict[str, Any]", cost) if isinstance(cost, dict) else {}
    models = cost.pop("models_used", [])
    blocks: Any = _mine("discipline_common", "mine_hook_blocks", session)
    try:
        done = teardown_steps.steps_done(teardown_steps.read_rows(state_dir))
    except ValueError:
        done = []
    retro: dict[str, Any] = {
        "schema_version": retro_check.SCHEMA,
        "status": "complete",
        "session_id": session,
        "loop_id": loop_id,
        "created": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "envelope": state.get("authorising_prompt_raw"),
        "loop_stop_counts": state.get("loop_stop_counts"),
        "decisions_absorbed": state.get("decisions_absorbed"),
        "disposition_record": retro_check.disposition_record(state),
        "evals": retro_check.evals_section(state_dir),
        "proof_results": retro_check.proof_summary(state_dir),
        "hook_blocks": blocks if isinstance(blocks, dict) else {},
        "models_used": models,
        "cost": cost,
        "teardown": {"steps_done": done},
        "memory": memory_section(session, cast("str | None", loop_id)),
        "source_hashes": hashes,
        "free": free or {},
    }
    handle, temp = tempfile.mkstemp(dir=str(state_dir), prefix="retro.json.tmp")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(retro, stream, indent=2, sort_keys=True)
        stream.write("\n")
    os.replace(temp, state_dir / "retro.json")
    degraded = [
        {"seq": s["seq"], "reason_code": s["muninn"]["reason_code"]}
        for s in flushed.get("synced", []) if s["muninn"]["state"] == "degraded"
    ]  # fmt: skip
    missing = [s for s in teardown_steps.REQUIRED if s not in done]
    _trace(session, loop_id, "degraded" if degraded else "assembled")
    return {"assembled": str(state_dir / "retro.json"), "degraded": degraded, "missing_steps": missing}, (
        3 if degraded else 0
    )


def _trace(session: str, loop_id: object, outcome: str) -> None:
    """Fail-open trace row `retro.assemble`."""
    try:
        runpy.run_path(str(ROOT / "hooks/scripts/lib/trace_row.py"))["append_row"](
            "retro.assemble",
            outcome,
            "ok" if outcome == "assembled" else "memory_degraded",
            session,
            cast("str | None", loop_id),
            None,
        )
    except Exception:  # noqa: BLE001
        return


def main(argv: list[str] | None = None) -> int:
    """CLI: assemble."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    asm = sub.add_parser("assemble")
    asm.add_argument("state_dir", type=Path)
    asm.add_argument("--session", required=True)
    asm.add_argument("--free-file", type=Path, default=None, help="JSON object stored under `free` (not hashed)")
    a = ap.parse_args(argv)
    free: dict[str, Any] | None = None
    if a.free_file:
        try:
            loaded: object = json.loads(a.free_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            loaded = None
        if not isinstance(loaded, dict):
            print(json.dumps({"reason_code": "retro_free_invalid"}))
            return 2
        free = cast("dict[str, Any]", loaded)
    payload, code = assemble(a.state_dir, a.session, free)
    print(json.dumps(payload, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
