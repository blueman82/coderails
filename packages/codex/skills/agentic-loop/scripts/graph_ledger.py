"""Decision and audit CLI options for the native Codex graph."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from graph_io import load as _load
from graph_vocab import disposition_report

COMMANDS = ("disposition-audit",)


def add_parsers(add: Callable[[str], argparse.ArgumentParser]) -> None:
    """Register the graph's decision and audit commands."""
    add("disposition-audit").add_argument("state", type=Path)
    for name in ("record-decision", "flush-decisions"):
        decision = add(name)
        decision.add_argument("state", type=Path)
        decision.add_argument("--session", required=True)
        decision.add_argument("--cite-quote")
        if name == "record-decision":
            decision.add_argument("--loop-id", required=True)
            decision.add_argument("--revision", required=True, type=int)
            decision.add_argument("--phase", required=True)
            decision.add_argument("--decision", required=True)
            decision.add_argument("--flip-condition")
            decision.add_argument("--unit")
            decision.add_argument("--chosen", help="answer to a recorded worker status")
            decision.add_argument("--worker-status-seq", type=int, help="resolve this worker status with the decision")
            decision.add_argument("--human-answer", action="store_true", help="human answered an approval gate")


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Return disposition status and a nonzero code for incomplete preserve-compat rows."""
    report = disposition_report(_load(args.state).get("work_units"))
    if report["offenders"]:
        print("graph: preserve-compat units must carry a named blocker and removal ticket", file=sys.stderr)
    return report, 1 if report["offenders"] else 0
