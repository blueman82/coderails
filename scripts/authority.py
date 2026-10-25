#!/usr/bin/env python3
"""Grant, inspect, narrow and revoke a session's authority object.

`grant` is the only way to mint one (the phrase 'crack on' no longer does).
crack_on_gate consumes it; per-action approvals live in action_receipt_cli.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.authority_object import (
    MERGE,
    authority_path,
    clear_legacy_flags,
    read_authority,
    validate,
    write_authority,
)


def refuse(code: str, message: str, session: str | None = None, loop: str | None = None) -> int:
    """Print a refusal to stderr, trace it under a stable reason code (when the session id is safe), exit 2."""
    print(f"authority: refused ({code}): {message}", file=sys.stderr)
    if session is not None:
        append_row("authority", "refused", code, session, loop)
    return 2


def missing_code(session: str) -> str | None:
    """Why read_authority returned None: missing / malformed / expired / invalid; None when foreign (already traced)."""
    path = authority_path(session)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path else None
    except FileNotFoundError:
        return "authority_refused_missing"
    except (OSError, ValueError):
        return "authority_refused_malformed"
    if not isinstance(raw, dict):
        return "authority_refused_malformed"
    data = cast("dict[str, Any]", raw)
    if data.get("session_id") != session:
        return None
    problems = validate(data, datetime.now(timezone.utc))
    return "authority_refused_expired" if problems == ["expired"] else "authority_refused_invalid"


def items(values: list[str] | None) -> list[str]:
    """Flatten repeated/comma-separated option values, dropping blanks and duplicates."""
    flat = [part.strip() for value in values or [] for part in value.split(",")]
    return list(dict.fromkeys(part for part in flat if part))


def grant(args: argparse.Namespace, path: Path) -> int:
    """Write a typed-grant object (granted_by=command); a live one is never replaced, an expired or torn one is."""
    if read_authority(args.session) is not None:
        return refuse(
            "authority_refused_exists", "an authority object already exists for this session", args.session, args.loop
        )
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
        "granted_by": "command",
    }
    problems = validate(obj, now)
    if problems:
        return refuse("authority_refused_create_invalid", ",".join(problems), args.session, args.loop)
    if not write_authority(path, obj):
        return refuse("authority_refused_write_failed", "write failed", args.session, args.loop)
    clear_legacy_flags(args.session)
    append_row("authority", "granted", "authority_granted_command", args.session, obj["loop_id"])
    print(json.dumps(obj, indent=2, sort_keys=True))
    return 0


def narrow(args: argparse.Namespace, current: dict[str, Any]) -> int:
    """Shrink scope (subset only) and/or max_prs (lower only); widening is refused."""
    loop = current["loop_id"]
    scope = items(args.scope) if args.scope is not None else None
    if scope is None and args.max_prs is None:
        return refuse("authority_refused_narrow_empty", "narrow needs --scope and/or --max-prs", args.session, loop)
    updated = dict(current)
    if scope is not None:
        if not set(scope) <= set(current["scope"]):
            return refuse("authority_refused_widen_scope", "scope may only shrink", args.session, loop)
        updated["scope"] = scope
    if args.max_prs is not None:
        if args.max_prs > current["max_prs"]:
            return refuse("authority_refused_widen_max_prs", "max_prs may only shrink", args.session, loop)
        updated["max_prs"] = args.max_prs
    problems = validate(updated, datetime.now(timezone.utc))
    path = authority_path(args.session)
    if problems or path is None or not write_authority(path, updated):
        code = "authority_refused_create_invalid" if problems else "authority_refused_write_failed"
        return refuse(code, ",".join(problems) or "write failed", args.session, loop)
    append_row("authority", "narrowed", "authority_narrowed", args.session, updated["loop_id"])
    print(json.dumps(updated, indent=2, sort_keys=True))
    return 0


def revoke(args: argparse.Namespace, current: dict[str, Any], path: Path) -> int:
    """Delete a revocable object; a non-revocable one is refused and left in place."""
    if not current["revocable"]:
        return refuse("authority_refused_not_revocable", "object is not revocable", args.session, current["loop_id"])
    try:
        path.unlink()
    except OSError:
        return refuse("authority_refused_write_failed", "delete failed", args.session, current["loop_id"])
    clear_legacy_flags(args.session)
    append_row("authority", "revoked", "authority_revoked", args.session, current["loop_id"])
    print(json.dumps({"revoked": current["authority_id"]}))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch one subcommand for one exact session id."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("grant", "create", "inspect", "narrow", "revoke"):  # create: one-release alias of grant
        command = sub.add_parser(name)
        minting = name in ("grant", "create")
        command.add_argument(
            "--session",
            required=not minting,
            default=None,
            help="exact session id (never sanitised)" + ("; default $CLAUDE_CODE_SESSION_ID" if minting else ""),
        )
        if minting:
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
    if args.command in ("grant", "create"):
        args.session = args.session or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    path = authority_path(args.session)
    if path is None:
        return refuse(
            "authority_refused_unsafe_session",
            "session id must start with a letter or digit; use only ASCII letters, digits, '.', '_' or '-'; no '..'",
        )
    if args.command in ("grant", "create"):
        return grant(args, path)
    current = read_authority(args.session)
    if args.command == "inspect":
        print(json.dumps(current, indent=2, sort_keys=True))
        return 0
    if current is None:
        code = missing_code(args.session)
        if code is None:  # foreign: read_authority already traced it
            return refuse("authority_refused_foreign", "no valid authority object for this session")
        return refuse(code, "no valid authority object for this session", args.session)
    return narrow(args, current) if args.command == "narrow" else revoke(args, current, path)


if __name__ == "__main__":
    raise SystemExit(main())
