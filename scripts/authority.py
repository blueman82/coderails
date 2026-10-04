#!/usr/bin/env python3
"""Create, inspect, narrow and revoke a session's authority object. Nothing consumes it yet (additive)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.authority_object import MERGE, authority_path, read_authority, validate, write_authority


def refuse(message: str) -> int:
    """Print a refusal to stderr and return the refusal exit status."""
    print(f"authority: refused: {message}", file=sys.stderr)
    return 2


def items(values: list[str] | None) -> list[str]:
    """Flatten repeated/comma-separated option values, dropping blanks and duplicates."""
    flat = [part.strip() for value in values or [] for part in value.split(",")]
    return list(dict.fromkeys(part for part in flat if part))


def create(args: argparse.Namespace, path: Path) -> int:
    """Write a new object; never overwrites, and merge approval is always required."""
    if path.exists():
        return refuse("an authority object already exists for this session")
    now = datetime.now(timezone.utc)
    obj: dict[str, Any] = {
        "authority_id": str(uuid.uuid4()),
        "loop_id": args.loop,
        "session_id": args.session,
        "scope": items(args.scope),
        "denied": items(args.denied),
        "max_prs": args.max_prs,
        "expires_at": (now + timedelta(hours=args.expires_in_hours)).isoformat(timespec="seconds"),
        "revocable": not args.not_revocable,
        "approval_required_for": list(dict.fromkeys([MERGE, *items(args.approval_for)])),
    }
    problems = validate(obj, now)
    if problems:
        return refuse(",".join(problems))
    if not write_authority(path, obj):
        return refuse("write failed")
    append_row("authority", "created", "authority_created", args.session, obj["loop_id"])
    print(json.dumps(obj, indent=2, sort_keys=True))
    return 0


def narrow(args: argparse.Namespace, current: dict[str, Any]) -> int:
    """Shrink scope (subset only) and/or max_prs (lower only); widening is refused."""
    scope = items(args.scope) if args.scope is not None else None
    if scope is None and args.max_prs is None:
        return refuse("narrow needs --scope and/or --max-prs")
    updated = dict(current)
    if scope is not None:
        if not set(scope) <= set(current["scope"]):
            return refuse("scope may only shrink")
        updated["scope"] = scope
    if args.max_prs is not None:
        if args.max_prs > current["max_prs"]:
            return refuse("max_prs may only shrink")
        updated["max_prs"] = args.max_prs
    problems = validate(updated, datetime.now(timezone.utc))
    path = authority_path(args.session)
    if problems or path is None or not write_authority(path, updated):
        return refuse(",".join(problems) or "write failed")
    append_row("authority", "narrowed", "authority_narrowed", args.session, updated["loop_id"])
    print(json.dumps(updated, indent=2, sort_keys=True))
    return 0


def revoke(args: argparse.Namespace, current: dict[str, Any], path: Path) -> int:
    """Delete a revocable object; a non-revocable one is refused and left in place."""
    if not current["revocable"]:
        return refuse("object is not revocable")
    try:
        path.unlink()
    except OSError:
        return refuse("delete failed")
    append_row("authority", "revoked", "authority_revoked", args.session, current["loop_id"])
    print(json.dumps({"revoked": current["authority_id"]}))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch one subcommand for one exact session id."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create", "inspect", "narrow", "revoke"):
        command = sub.add_parser(name)
        command.add_argument("--session", required=True, help="exact session id (never sanitised)")
        if name == "create":
            command.add_argument("--loop", default=None)
            command.add_argument("--scope", action="append", default=[])
            command.add_argument("--denied", action="append", default=[])
            command.add_argument("--max-prs", type=int, required=True)
            command.add_argument("--expires-in-hours", type=float, default=24.0)
            command.add_argument("--not-revocable", action="store_true")
            command.add_argument("--approval-for", action="append", default=[])
        if name == "narrow":
            command.add_argument("--scope", action="append", default=None)
            command.add_argument("--max-prs", type=int, default=None)
    args = parser.parse_args(argv)
    path = authority_path(args.session)
    if path is None:
        return refuse("session id must be nonempty and contain no '/' or '..'")
    if args.command == "create":
        return create(args, path)
    current = read_authority(args.session)
    if args.command == "inspect":
        print(json.dumps(current, indent=2, sort_keys=True))
        return 0
    if current is None:
        return refuse("no valid authority object for this session")
    return narrow(args, current) if args.command == "narrow" else revoke(args, current, path)


if __name__ == "__main__":
    raise SystemExit(main())
