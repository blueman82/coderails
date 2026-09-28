#!/usr/bin/env python3
"""Operate the native Claude schema-v3 graph through its provider-owned adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_dispatch as dispatch
from hooks.scripts.lib.graph_evidence import object_value
from hooks.scripts.lib.graph_executor import graph_semantics, load, transition


def parser() -> argparse.ArgumentParser:
    """Expose only current semantic operations and native completion checks."""
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in (
        "inspect",
        "plan",
        "begin-wave",
        "record-wave",
        "respawn-stale",
        "hard-stop",
        "authorize-dispatch",
        "complete",
        "verify-completion",
    ):
        command = commands.add_parser(name)
        command.add_argument("state", type=Path)
        if name == "record-wave":
            command.add_argument("results_json")
        if name in {"respawn-stale", "hard-stop", "authorize-dispatch", "complete", "verify-completion"}:
            command.add_argument("--session", required=True)
        if name in {"respawn-stale", "hard-stop"}:
            command.add_argument("--node", required=True)
            command.add_argument("--reason", required=True)
        if name == "authorize-dispatch":
            command.add_argument("--prompt", required=True)
            command.add_argument("--subagent-type", required=True)
    return result


def native_transition(path: Path, session: str, operation: str, node: str, reason: str) -> dict[str, Any]:
    """Apply one pure transition under the sole Claude lock and owner check."""
    output: dict[str, Any] = {}

    def update(state: dict[str, Any]) -> dict[str, Any]:
        if state["session_id"] != session:
            raise ValueError("session does not own this graph")
        transform = graph_semantics.respawn_stale if operation == "respawn_stale" else graph_semantics.hard_stop
        proposal = transform(state, node, reason)
        output.update({key: value for key, value in proposal.items() if key != "state"})
        return object_value(proposal["state"], "proposed graph")

    transition(path, update)
    return output


def main() -> int:
    """Run one explicit graph operation with fail-closed CLI status."""
    args = parser().parse_args()
    try:
        if args.command == "inspect":
            state = load(args.state)
            output: object = {
                "session_id": state["session_id"],
                "loop_id": state["loop_id"],
                **graph_semantics.inspect(state),
            }
        elif args.command == "plan":
            output = dispatch.plan(args.state)
        elif args.command == "begin-wave":
            output = dispatch.begin_wave(args.state)
        elif args.command == "record-wave":
            output = dispatch.record_wave(args.state, object_value(json.loads(args.results_json), "wave report"))
        elif args.command in {"respawn-stale", "hard-stop"}:
            output = native_transition(args.state, args.session, args.command.replace("-", "_"), args.node, args.reason)
        elif args.command == "authorize-dispatch":
            output = dispatch.authorize_dispatch(args.state, args.session, args.prompt, args.subagent_type)
        else:
            output = dispatch.complete(args.state, args.session, args.command == "complete")
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(f"graph: {error}", file=sys.stderr)
        return 1
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
