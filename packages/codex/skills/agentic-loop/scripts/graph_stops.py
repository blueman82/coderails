"""Native Codex stop-intent rows for `progress.stops`: pure row core plus the locked CLI operations."""

from __future__ import annotations

import argparse
import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_identity import GraphError
from graph_io import load as _load
from graph_io import locked as _locked
from graph_io import write as _write

STOP_CATEGORIES = ("hard-stop", "approval-gate", "awaiting-input", "complete")
STOP_REASON_CODES = (
    "work_complete",
    "needs_human_input",
    "needs_approval",
    "node_hard_stop",
    "environment_blocked",
    "other",
)


def record_stop(state: object, session: str, category: str, reason_code: str, reason: str) -> dict[str, Any]:
    """Propose the state with one more unconsumed stop row bound to the current revision."""
    root = copy.deepcopy(graph_semantics.validate(state))
    refusals = (
        (root.get("session_id") != session, "session", "session does not own this graph"),
        (category not in STOP_CATEGORIES, "stop_category", "category must be one of " + ", ".join(STOP_CATEGORIES)),
        (reason_code not in STOP_REASON_CODES, "stop_reason_code", "unknown reason_code"),
        (not reason.strip(), "stop_reason", "reason must be a non-empty string"),
        (
            category == "complete" and not graph_semantics.can_complete(root)["eligible"],
            "stop_complete",
            "complete requires a resolved graph",
        ),
    )
    for refused, code, message in refusals:
        if refused:
            raise graph_semantics.GraphSemanticError(code, message)
    stops = root.setdefault("stops", [])
    if not isinstance(stops, list) or not all(isinstance(row, dict) for row in cast(list[object], stops)):
        raise graph_semantics.GraphSemanticError("shape", "stops must be an array of objects")
    rows = cast(list[dict[str, Any]], stops)
    seq = max((row["seq"] for row in rows if isinstance(row.get("seq"), int)), default=0) + 1
    row = {
        "seq": seq,
        "category": category,
        "reason_code": reason_code,
        "reason": reason,
        "revision": root["revision"],
        "consumed": False,
    }
    rows.append(row)
    return {"state": root, "stop": copy.deepcopy(row)}


def record(path: Path, session: str, category: str, reason_code: str, reason: str) -> dict[str, Any]:
    """Append one stop-intent row under the state lock and owner check."""
    with _locked(path):
        try:
            proposal = record_stop(_load(path), session, category, reason_code, reason)
        except ValueError as error:
            raise GraphError(str(error)) from error
        _write(path, proposal["state"])
        return cast(dict[str, Any], proposal["stop"])


def consume(path: Path, session: str) -> dict[str, Any]:
    """Consume the newest unconsumed same-revision hard-stop row; the Stop guard releases only on a hit."""
    with _locked(path):
        state = _load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        rows = cast(object, state.get("stops"))
        for row in reversed(cast(list[object], rows) if isinstance(rows, list) else []):
            stop = cast(dict[str, Any], row) if isinstance(row, dict) else {}
            current = stop.get("consumed") is False and stop.get("revision") == state["revision"]
            if current and stop.get("category") == "hard-stop":
                stop["consumed"] = True
                _write(path, state)
                return {"stop": stop}
        return {"stop": None}


def add_parsers(add: Callable[[str], argparse.ArgumentParser]) -> None:
    """Register `stop` and `consume-stop` on a subparsers action's add_parser."""
    stop = add("stop")
    stop.add_argument("--category", required=True, choices=STOP_CATEGORIES)
    stop.add_argument("--reason-code", required=True, choices=STOP_REASON_CODES)
    stop.add_argument("--reason", required=True)
    for command in (stop, add("consume-stop")):
        command.add_argument("state", type=Path)
        command.add_argument("--session", required=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the parsed stop or consume-stop command."""
    if args.command == "stop":
        return record(args.state, args.session, args.category, args.reason_code, args.reason)
    return consume(args.state, args.session)
