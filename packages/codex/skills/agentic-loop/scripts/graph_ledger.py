"""Native Codex read-only audits and ledger commands that sit beside the main graph CLI: `disposition-audit`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from graph_io import load as _load
from graph_vocab import disposition_report

COMMANDS = ("disposition-audit",)


def add_parsers(add: Callable[[str], argparse.ArgumentParser]) -> None:
    """Register the ledger commands on a subparsers action's add_parser."""
    add("disposition-audit").add_argument("state", type=Path)


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Execute the parsed command; return (output, exit code)."""
    report = disposition_report(_load(args.state).get("work_units"))
    return report, 1 if report["offenders"] else 0
