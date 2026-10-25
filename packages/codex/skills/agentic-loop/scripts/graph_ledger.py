"""Read-only disposition audit for the native Codex graph CLI."""

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
    """Register the disposition audit on a subparsers action's add_parser."""
    add("disposition-audit").add_argument("state", type=Path)


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Return disposition status and a nonzero code for incomplete preserve-compat rows."""
    report = disposition_report(_load(args.state).get("work_units"))
    if report["offenders"]:
        print("graph: preserve-compat units must carry a named blocker and removal ticket", file=sys.stderr)
    return report, 1 if report["offenders"] else 0
