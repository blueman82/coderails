#!/usr/bin/env python3
"""Mint, inspect and revoke signed action receipts (approval bound to repository + ref + SHA + exact command).

OWNER-RUN: approve-action computes the binding itself (the owner never types a SHA), signs with the
passphrase-protected owner key and refuses without a controlling terminal (receipt_refused_no_tty), so an agent
that lacks the passphrase cannot mint. With the user-tier trust root this is a cooperating-agent safeguard, not a
boundary; see docs/decisions/p3-human-only-minting.md. Receipts are always single-use.
Limits: scope <= 500 chars, 50 receipts per session.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hooks.scripts.lib.trace_row import append_row
from scripts.lib import action_receipt as ar
from scripts.lib import receipt_signing as rs
from scripts.lib.action_binding import binding, git_out
from scripts.lib.authority_object import read_authority

KINDS = ("merge", "git_push")


def refuse(code: str, message: str, session: str | None = None, loop: str | None = None) -> int:
    """Print a refusal to stderr, trace it under a stable reason code, exit 2."""
    print(f"action-receipt: refused ({code}): {message}", file=sys.stderr)
    if session is not None:
        append_row("action_receipt", "refused", code, session, loop)
    return 2


def approve(args: argparse.Namespace) -> int:
    """Write one new signed receipt for the exact command, cwd, branch and computed binding; never overwrites."""
    now = datetime.now(timezone.utc)
    cwd = args.cwd or str(Path.cwd())
    if len(args.scope) > ar.MAX_SCOPE:
        return refuse("receipt_refused_scope_too_long", f"scope over {ar.MAX_SCOPE} chars", args.session, args.loop)
    bind = binding(args.kind, args.action_command, cwd)
    if bind is None:
        return refuse("receipt_refused_binding_unknown", "cannot compute repository+ref+sha", args.session, args.loop)
    branch = args.branch if args.branch is not None else git_out(cwd, "branch", "--show-current")
    try:
        hours = args.expires_in_hours
        if not math.isfinite(hours) or hours <= 0:
            raise ValueError("expiry must be finite and positive")
        expires = (now + timedelta(hours=hours)).isoformat(timespec="seconds")
    except (OverflowError, ValueError) as error:
        return refuse("receipt_refused_expiry_invalid", str(error), args.session, args.loop)
    proposed = ar.proposed_action(args.kind, args.action_command, cwd, branch, bind)
    receipt_id = str(uuid.uuid4())
    live = read_authority(args.session)
    obj: dict[str, Any] = {
        "receipt_id": receipt_id,
        "authority_id": args.authority_id or (live["authority_id"] if live else None),  # max_prs counts by this id
        "session_id": args.session,
        "loop_id": args.loop,
        "action": args.kind,
        "exact_payload_hash": proposed["exact_payload_hash"],
        "repository": bind["repository"],
        "ref": bind["ref"],
        "artifact_sha": bind["sha"],
        "nonce": uuid.uuid4().hex,
        "scope": args.scope,
        "issued_at": now.isoformat(timespec="seconds"),
        "expires_at": expires,
        "single_use": True,
        "revoked": False,
        "signature": None,
    }
    try:
        obj["signature"] = rs.sign(ar.body_text(obj), Path(args.key) if args.key else rs.keys_dir() / "receipt_ed25519")
    except rs.SigningError as error:
        return refuse(f"receipt_refused_{error.code}", str(error), args.session, args.loop)
    signers = Path(args.signers) if args.signers else rs.resolve_trust_root()[0]
    path = ar.receipt_path(args.session, receipt_id)
    ok, code = ar.verify(obj, proposed, now, args.session, args.loop, signers=signers)
    if path is None or not ok:
        return refuse(f"receipt_refused_{code}", "receipt would not verify", args.session, args.loop)
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


def main(argv: list[str] | None = None, tty_ok: Callable[[], bool] = rs.have_tty) -> int:
    """Dispatch one subcommand. tty_ok is a function argument (tests only): no flag or env var can skip the tty rule."""
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
    mint.add_argument("--key", default=None, help="owner private key (default ~/.coderails/keys/receipt_ed25519)")
    mint.add_argument("--signers", default=None, help="signers file to self-verify against (default: trust root)")
    mint.add_argument("--scope", default="")
    mint.add_argument("--expires-in-hours", type=float, default=1.0)
    for name in ("inspect-receipt", "revoke-receipt"):
        other = sub.add_parser(name)
        other.add_argument("--session", required=True)
        other.add_argument("--receipt-id", required=True)
    args = parser.parse_args(argv)
    if args.command == "approve-action":
        if not tty_ok():
            return refuse("receipt_refused_no_tty", "minting needs the owner at a terminal", args.session, args.loop)
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
