"""Build the native Codex graph command parser."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import graph_ledger
import graph_spec
import graph_stops
from graph_vocab import DISPOSITION_KINDS


def _add_unit_args(controller: argparse.ArgumentParser) -> None:
    """Register work-unit ownership and disposition fields."""
    controller.add_argument("--unit", required=True)
    controller.add_argument("--depends-on", action="append", default=[])
    controller.add_argument("--join", action="store_true")
    controller.add_argument("--manifest", action="append", default=[])
    controller.add_argument("--base-branch", help="remote branch used for first stacked publication")
    controller.add_argument("--worktree", help="absolute path of this unit's checkout")
    controller.add_argument("--model-role", help="dispatch model class: fast-mechanical | default | frontier")
    controller.add_argument("--write-scope", action="append", default=[], help="path the worker may write")
    controller.add_argument("--lesson", action="append", default=[], help="lesson the worker prompt must carry")
    controller.add_argument("--scope", help="one-line scope statement for the worker")
    controller.add_argument("--disposition", choices=DISPOSITION_KINDS, help="clean-break | preserve-compat")
    controller.add_argument("--named-blocker", help="what blocks removal (preserve-compat only)")
    controller.add_argument("--removal-ticket", help="ticket that removes it (preserve-compat only)")


def _decision_args(commands: Any) -> None:  # noqa: ANN401 - argparse exposes no public subparser action type
    """Add the typed decision commands."""
    for name in ("record-decision", "flush-decisions"):
        decision = commands.add_parser(name)
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
            decision.add_argument(
                "--human-answer", action="store_true", help="a human answered an approval-gate status"
            )


def parser() -> argparse.ArgumentParser:
    """Construct the native graph command parser."""
    parser = argparse.ArgumentParser(description="Operate one native Codex agentic-loop graph.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("begin-wave", "inspect", "summarize", "collection"):
        command = commands.add_parser(name)
        command.add_argument("root" if name == "collection" else "state", type=Path)
    for name in ("start", "add-unit"):
        controller = commands.add_parser(name)
        controller.add_argument("state", type=Path)
        controller.add_argument("--session", required=True)
        controller.add_argument("--loop-id", required=True)
        if name == "start":
            controller.add_argument("--prompt-file", required=True, type=Path)
        else:
            _add_unit_args(controller)
    graph_ledger.add_parsers(commands.add_parser)
    spec = commands.add_parser("instantiate")
    spec.add_argument("state", type=Path)
    spec.add_argument("--session", required=True)
    spec.add_argument("--loop-id", required=True)
    spec.add_argument("--profile", choices=graph_spec.PROFILES, help="default: policy graph.profile")
    spec.add_argument("--unit", action="append", default=[], help="work unit id to register (repeatable)")
    convert = commands.add_parser("convert")
    convert.add_argument("state", type=Path)
    convert.add_argument("--session", required=True)
    mode = convert.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    recover = commands.add_parser("recover-wave")
    recover.add_argument("state", type=Path)
    recover.add_argument("--session", required=True)
    recover.add_argument("--lease-seconds", type=int, default=900)
    recover.add_argument("--report-only", action="store_true")
    reject = commands.add_parser("reject-invalid-dispatch")
    reject.add_argument("state", type=Path)
    reject.add_argument("--session", required=True)
    reject.add_argument("--node", required=True)
    reject.add_argument("--wave-id", required=True)
    reject.add_argument("--report-only", action="store_true")
    record = commands.add_parser("record-wave")
    record.add_argument("state", type=Path)
    record.add_argument("results_json")
    _decision_args(commands)
    unit = commands.add_parser("record-unit")
    unit.add_argument("state", type=Path)
    unit.add_argument("--session", required=True)
    unit.add_argument("--unit", required=True)
    unit.add_argument("--status", required=True, choices=("done", "dropped"))
    detail = unit.add_mutually_exclusive_group(required=True)
    detail.add_argument("--evidence")
    detail.add_argument("--reason")
    repair = commands.add_parser("record-repair")
    repair.add_argument("state", type=Path)
    for field in ("session", "unit", "failed-node", "kind", "identity", "diagnosis"):
        repair.add_argument(f"--{field}", required=True)
    disposition = commands.add_parser("record-proof-disposition")
    disposition.add_argument("state", type=Path)
    disposition.add_argument("--session", required=True)
    disposition.add_argument("--loop-id", required=True)
    disposition.add_argument("--revision", required=True, type=int)
    disposition.add_argument("--disposition", required=True)
    disposition.add_argument("--reason", required=True)
    for name in ("respawn_stale", "hard_stop"):
        transition = commands.add_parser(name.replace("_", "-"))
        transition.add_argument("state", type=Path)
        transition.add_argument("--session", required=True)
        transition.add_argument("--node", required=True)
        transition.add_argument("--reason", required=True)
    graph_stops.add_parsers(commands.add_parser)
    dispatch = commands.add_parser("authorize-dispatch")
    dispatch.add_argument("state", type=Path)
    for option in ("session", "dispatch-id", "task-name"):
        dispatch.add_argument(f"--{option}", required=True)
    dispatch.add_argument("--message-file", required=True, type=Path)
    dispatch.add_argument("--agent-type", default="", help="the spawn_agent agent_type; empty when none was given")
    dispatch.add_argument("--tool-use-id", default="", help="native tool-call id from PreToolUse")
    dispatch.add_argument("--evals", type=Path, help="default: evals.json beside the state")
    for name in ("complete", "verify-completion"):
        complete = commands.add_parser(name)
        complete.add_argument("state", type=Path)
        complete.add_argument("--session", required=True)
        for option in ("evals", "proof", "retro"):
            complete.add_argument(f"--{option}", required=True, type=Path)
        complete.add_argument("--transcript", type=Path)
    return parser
