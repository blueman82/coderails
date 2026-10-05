#!/usr/bin/env python3
"""Mint, inspect and revoke action receipts (approval bound to one exact command).

A receipt binds an approval to an exact action; it does NOT prove a human approved it: a same-user agent can run
approve-action too. Hash coverage is the command text the hook sees (not aliases, functions, eval).
Limits: scope <= 500 chars, 50 receipts per session.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.destructive_patterns import git_output
from hooks.scripts.lib.trace_row import append_row
from scripts.lib import action_receipt as ar

KINDS = ("merge", "git_push")


def refuse(code: str, message: str, session: str | None = None, loop: str | None = None) -> int:
    """Print a refusal to stderr, trace it under a stable reason code, exit 2."""
    print(f"action-receipt: refused ({code}): {message}", file=sys.stderr)
    if session is not None:
        append_row("action_receipt", "refused", code, session, loop)
    return 2


def approve(args: argparse.Namespace) -> int:
    """Write one new receipt for the exact command, cwd and branch; never overwrites."""
    now = datetime.now(timezone.utc)
    cwd = args.cwd or str(Path.cwd())
    branch = args.branch if args.branch is not None else git_output(cwd, "branch", "--show-current")
    proposed = ar.proposed_action(args.kind, args.action_command, cwd, branch, args.artifact_sha)
    if len(args.scope) > ar.MAX_SCOPE:
        return refuse("receipt_refused_scope_too_long", f"scope over {ar.MAX_SCOPE} chars", args.session, args.loop)
    receipt_id = str(uuid.uuid4())
    obj: dict[str, Any] = {
        "receipt_id": receipt_id,
        "authority_id": args.authority_id,
        "session_id": args.session,
        "loop_id": args.loop,
        "action": args.kind,
        "exact_payload_hash": proposed["exact_payload_hash"],
        "artifact_sha": args.artifact_sha,
        "scope": args.scope,
        "issued_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(hours=args.expires_in_hours)).isoformat(timespec="seconds"),
        "single_use": not args.reusable,
        "revoked": False,
    }
    path = ar.receipt_path(args.session, receipt_id)
    ok, code = ar.verify(obj, proposed, now, args.session, args.loop)
    if path is None or not ok:
        return refuse(f"receipt_refused_{code}", "receipt would be invalid", args.session, args.loop)
    if len(list(path.parent.glob("*.json"))) >= ar.MAX_RECEIPTS:
        return refuse("receipt_refused_too_many", f"over {ar.MAX_RECEIPTS} receipts", args.session, args.loop)
    if not ar.write_receipt(path, obj):
        return refuse("receipt_refused_write_failed", "write failed", args.session, args.loop)
    append_row("action_receipt", "approved", "receipt_approved", args.session, args.loop)
    print(json.dumps(obj, indent=2, sort_keys=True))
    return 0


def locate(args: argparse.Namespace) -> tuple[Path, dict[str, Any]] | int:
    """Find this session's receipt by exact id; refuse missing, unreadable and foreign-session files."""
    path = ar.receipt_path(args.session, args.receipt_id)
    if path is None:
        return refuse("receipt_refused_unsafe_id", "session and receipt ids must be path-local")
    data = ar.effective(path)
    if data is None:
        return refuse("receipt_refused_missing", "no readable receipt with that id", args.session)
    if data.get("session_id") != args.session:
        return refuse("receipt_refused_foreign_session", "receipt belongs to another session", args.session)
    return path, data


def main(argv: list[str] | None = None) -> int:
    """Dispatch one subcommand."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    mint = sub.add_parser("approve-action")
    mint.add_argument("--session", required=True)
    mint.add_argument("--loop", default=None)
    mint.add_argument("--authority-id", default=None)
    mint.add_argument("--kind", choices=KINDS, required=True)
    mint.add_argument("--command", dest="action_command", required=True, help="exact command text the hook sees")
    mint.add_argument("--cwd", default=None)
    mint.add_argument("--branch", default=None, help="default: current branch of --cwd")
    mint.add_argument("--artifact-sha", default=None)
    mint.add_argument("--scope", default="")
    mint.add_argument("--expires-in-hours", type=float, default=1.0)
    mint.add_argument("--reusable", action="store_true")
    for name in ("inspect-receipt", "revoke-receipt"):
        other = sub.add_parser(name)
        other.add_argument("--session", required=True)
        other.add_argument("--receipt-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "approve-action":
        return approve(args)
    found = locate(args)
    if isinstance(found, int):
        return found
    path, data = found
    if args.command == "inspect-receipt":
        print(json.dumps({**data, "consumed": ar.is_consumed(path)}, indent=2, sort_keys=True))
        return 0
    if not ar.revoke_receipt(path):
        return refuse("receipt_refused_already_revoked", "receipt already revoked", args.session)
    append_row("action_receipt", "revoked", "receipt_revoked", args.session, data["loop_id"])
    print(json.dumps({"revoked": data["receipt_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
