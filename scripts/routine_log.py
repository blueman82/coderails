#!/usr/bin/env python3
"""Append one routine event row (closed outcome enum, closed per-routine reason codes) and derive the legacy marker.

`emit --log PATH --run-id ID --routine NAME --stage S --outcome O [--reason-code C] [--human-log PATH]` appends
{v,ts,run_id,routine,stage,outcome,reason_code} to JSONL, then the legacy marker to the human log under
a file lock. The dashboard's last-marker predicate keeps working unchanged. An outcome or code outside the closed lists
exits 2 and appends nothing.
Reason codes come from routines/<routine>.json beside this script's plugin root.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

OUTCOMES = ("stage_ok", "run_ok", "run_abort", "run_refused", "run_incomplete")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # so hooks.scripts.lib.trace_row imports when run as a script


def load_spec(routine: str, spec: str | Path | None = None) -> dict[str, Any] | None:
    """Return routines/<routine>.json (or the given file) as a dict, or None when absent, torn or the name is unsafe."""
    if spec is None and not re.fullmatch(r"[a-z0-9-]+", routine):
        return None
    try:
        data = json.loads(Path(spec or ROOT / "routines" / f"{routine}.json").read_text())
    except (OSError, ValueError):
        return None
    return cast(dict[str, Any], data) if isinstance(data, dict) else None


def marker(outcome: str, stage: str, reason_code: str) -> str:
    """The legacy human-log text for a row: run=ok, abort=<code>, refused=<gate>, abort=incomplete-run, stage=<name>."""
    return {
        "run_ok": "run=ok",
        "run_abort": f"abort={reason_code}",
        "run_refused": f"refused={reason_code}",
        "run_incomplete": {
            "merged_incomplete": "incomplete=merged",
            "merge_state_unknown": "incomplete=merge-unknown",
        }.get(reason_code, "abort=incomplete-run"),
    }.get(outcome, f"stage={stage}")


def validate(spec: dict[str, Any] | None, routine: str, outcome: str, reason_code: str) -> str:
    """Return '' when the row is allowed, else the refusal code."""
    if spec is None or spec.get("routine") != routine:
        return "routine_unknown"
    if outcome not in OUTCOMES:
        return "outcome_invalid"
    needs_code = outcome in ("run_abort", "run_refused", "run_incomplete")
    codes = spec.get("reason_codes")
    if needs_code != bool(reason_code) or (needs_code and (not isinstance(codes, list) or reason_code not in codes)):
        return "reason_code_invalid"
    return ""


def trace(routine: str, outcome: str, reason_code: str) -> None:
    """Best-effort `routine/<outcome>/<code>` counter row; never raises."""
    try:
        module = importlib.import_module("hooks.scripts.lib.trace_row")
        module.append_row("routine", outcome, reason_code or "none", routine)
    except Exception:  # fail open: a trace row never decides anything
        return


def emit(
    log: str | Path,
    run_id: str,
    routine: str,
    stage: str,
    outcome: str,
    reason_code: str = "",
    human_log: str | Path | None = None,
    spec: dict[str, Any] | None = None,
) -> str:
    """Validate then append the row and its derived marker; returns '' on success or the refusal code."""
    refusal = validate(spec if spec is not None else load_spec(routine), routine, outcome, reason_code)
    if refusal or not run_id or not stage:
        return refusal or "field_missing"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row = {
        "v": 1,
        "ts": now,
        "run_id": run_id,
        "routine": routine,
        "stage": stage,
        "outcome": outcome,
        "reason_code": reason_code,
    }
    path = Path(log)
    human = Path(human_log) if human_log else path.with_suffix(".log")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        human.parent.mkdir(parents=True, exist_ok=True)
        with Path(f"{path}.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with path.open("a", encoding="utf-8") as stream, human.open("a", encoding="utf-8") as human_stream:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
                human_stream.write(f"{now} run_id={run_id} {marker(outcome, stage, reason_code)}\n")
    except OSError:
        return "log_unwritable"
    trace(routine, outcome, reason_code)
    return ""


def main(arguments: list[str] | None = None) -> int:
    """CLI entry: only the `emit` subcommand exists."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True).add_parser("emit")
    for name in ("log", "run-id", "routine", "stage", "outcome"):
        sub.add_argument(f"--{name}", required=True)
    sub.add_argument("--reason-code", default="")
    sub.add_argument("--human-log")
    args = parser.parse_args(arguments)
    refusal = emit(args.log, args.run_id, args.routine, args.stage, args.outcome, args.reason_code, args.human_log)
    if refusal:
        print(refusal, file=sys.stderr)
    return 2 if refusal else 0


if __name__ == "__main__":
    raise SystemExit(main())
