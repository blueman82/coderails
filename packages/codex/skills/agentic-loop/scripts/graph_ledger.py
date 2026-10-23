"""Native Codex ledger commands beside the main graph CLI: read-only `disposition-audit`, locked `record-decision`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import worker_status
from graph_identity import GraphError
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import write as _write
from graph_recovery import trace
from graph_vocab import disposition_report

COMMANDS = ("disposition-audit", "record-decision")


def record_decision(
    path: Path,
    session: str,
    fields: dict[str, str | None],
    worker_status_seq: int | None = None,
    human_answer: bool = False,
) -> dict[str, Any]:
    """Append one typed ledger row under the state lock and owner check; a refusal writes nothing but a trace row."""
    inputs: dict[str, Any] = {"session": session, **fields, "worker_status_seq": worker_status_seq}
    with _locked(path):
        state = _load(path)
        try:
            proposed, row = worker_status.append_decision(state, session, fields, worker_status_seq, human_answer)
        except worker_status.WorkerResultError as error:
            trace(path, state, "refused", error.code, inputs, [], "record-decision")
            raise GraphError(str(error)) from error
        _write(path, proposed)
    trace(path, proposed, "recorded", "decision_recorded", inputs, [], "record-decision")
    return row


def add_parsers(add: Callable[[str], argparse.ArgumentParser]) -> None:
    """Register the ledger commands on a subparsers action's add_parser."""
    add("disposition-audit").add_argument("state", type=Path)
    decision = add("record-decision")
    decision.add_argument("state", type=Path)
    decision.add_argument("--session", required=True)
    for flag in ("--phase", "--decision", "--chosen"):
        decision.add_argument(flag, required=True)
    decision.add_argument("--flip-condition", help="what would change this decision")
    decision.add_argument("--worker-status-seq", type=int, help="mark this worker_statuses row resolved")
    decision.add_argument("--human-answer", action="store_true", help="a human answered (approval-gate statuses)")


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Execute the parsed command; return (output, exit code)."""
    if args.command == "record-decision":
        typed: dict[str, str | None] = {"phase": args.phase, "decision": args.decision, "chosen": args.chosen}
        typed["flip_condition"] = args.flip_condition
        return record_decision(args.state, args.session, typed, args.worker_status_seq, args.human_answer), 0
    report = disposition_report(_load(args.state).get("work_units"))
    if report["offenders"]:
        print("graph: preserve-compat units must carry a named blocker and removal ticket", file=sys.stderr)
    return report, 1 if report["offenders"] else 0
