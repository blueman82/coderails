"""Build the Claude graph unit registration command."""

from __future__ import annotations

import argparse

from graph_vocab import DISPOSITION_KINDS


def add_unit_args(command: argparse.ArgumentParser) -> None:
    """Register the owned work-unit fields and its disposition boundary."""
    command.add_argument("--unit", required=True)
    command.add_argument("--depends-on", action="append", default=[])
    command.add_argument("--join", action="store_true")
    command.add_argument("--manifest", action="append", default=[])
    command.add_argument("--base-branch", help="remote branch used for first stacked publication")
    command.add_argument("--worktree", help="absolute path of this unit's checkout")
    command.add_argument("--model-role", help="dispatch model class: fast-mechanical | default | frontier")
    command.add_argument("--write-scope", action="append", default=[], help="path the worker may write")
    command.add_argument("--lesson", action="append", default=[], help="lesson the worker prompt must carry")
    command.add_argument("--scope", help="one-line scope statement for the worker")
    command.add_argument("--disposition", choices=DISPOSITION_KINDS, help="clean-break | preserve-compat")
    command.add_argument("--named-blocker", help="what blocks removal (preserve-compat only)")
    command.add_argument("--removal-ticket", help="ticket that removes it (preserve-compat only)")
