"""Join native graph completion to the durable standing-orders lifecycle."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from scripts.lib import orders as order_cli
from scripts.lib import orders_ledger as ol
from scripts.lib import orders_lifecycle as lifecycle
from scripts.lib.memory_adapter import MARKER

ROOT = Path(__file__).resolve().parents[2]
VIEWS = ("standing-orders.md", "standing-orders-decayed.md")


def _call(path: Path, session: str, command: str, loop: str) -> tuple[int, dict[str, Any]]:
    """Use the installed provider CLI outside the progress and orders locks."""
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/lib/orders.py"),
            "--dir",
            str(path.parent.parent),
            "--session",
            session,
            command,
            "--loop",
            loop,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    try:
        payload: object = json.loads(process.stdout)
    except (ValueError, TypeError) as error:
        raise ValueError(f"orders {command} returned invalid output") from error
    if not isinstance(payload, dict):
        raise ValueError(f"orders {command} returned invalid output")
    return process.returncode, cast(dict[str, Any], payload)


def prepare(path: Path, session: str, loop: str) -> str:
    """Prepare the exact current source before native progress is locked."""
    try:
        code, payload = _call(path, session, "prepare", loop)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("orders prepare unavailable") from error
    digest = payload.get("evidence_sha256")
    if code or payload.get("prepared") is not True or not isinstance(digest, str):
        raise ValueError(f"orders prepare refused: {payload.get('reason_code', code)}")
    return digest


def validate_prepared(path: Path, state: dict[str, Any], digest: str) -> None:
    """Re-read the prepared source under the native graph lock before its durable save."""
    source = lifecycle.source_state(state)
    binding = {
        "repo_dir": str(path.parent.parent.resolve()),
        "state_dir": str(path.parent.resolve()),
        "session_id": state["session_id"],
        "loop_id": state["loop_id"],
        "revision": source["revision"],
        "progress_sha256": lifecycle.sha(source),
    }
    staged = lifecycle.prepared(path.parent, binding, required=True)
    if lifecycle.sha(staged) != digest:
        raise ValueError("order_source_mismatch")


def _view_digest(repo_dir: Path, ledger: ol.Ledger) -> str:
    """Bind the saved ledger and both generated read-only views to one receipt."""
    views: dict[str, str] = {}
    for name in VIEWS:
        path = repo_dir / name
        if path.is_symlink() or path.stat().st_mode & 0o777 != 0o444:
            raise ValueError("order_pending_teardown")
        content = path.read_bytes()
        if not content.startswith(MARKER.encode()):
            raise ValueError("order_pending_teardown")
        views[name] = hashlib.sha256(content).hexdigest()
    return lifecycle.sha({"ledger": ledger, "views": views})


def status(path: Path, session: str) -> None:
    """Refuse a complete loop whose tick or rendered views lack current bound receipts."""
    repo_dir = path.parent.parent
    source = lifecycle.object_file(path)
    loop = source.get("loop_id")
    if not isinstance(loop, str) or not loop.strip():
        raise ValueError("order_wrong_session")
    with order_cli.locked(repo_dir):
        ledger = ol.open_ledger(repo_dir)
        state_dir, state, binding = lifecycle.owned(repo_dir, session, loop, complete=True)
        staged = lifecycle.prepared(state_dir, binding, required=True)
        digest = lifecycle.sha(staged)
        if lifecycle.loop_key(session, state["loop_id"]) not in ledger["ticked_loops"]:
            raise ValueError("order_pending_teardown")
        if not lifecycle.observe(state_dir, "orders_ticked", binding, digest, emit=False):
            raise ValueError("order_pending_teardown")
        rendered = _view_digest(repo_dir, ledger)
        if not lifecycle.observe(state_dir, "orders_rendered", binding, rendered, emit=False):
            raise ValueError("order_pending_teardown")


def finish(path: Path, session: str, loop: str) -> dict[str, Any]:
    """Resume idempotent tick and render after the native graph lock is released."""
    result: dict[str, Any] = {"pending_teardown": True, "exit_code": 3, "reason_code": "order_pending_teardown"}
    try:
        tick_code, tick = _call(path, session, "tick", loop)
        result["tick"] = {"exit_code": tick_code, **tick}
        if tick_code not in (0, 3):
            return result
        render_code, render = _call(path, session, "render", loop)
        result["render"] = {"exit_code": render_code, **render}
        if render_code == 0:
            repo_dir = path.parent.parent
            with order_cli.locked(repo_dir):
                ledger = ol.open_ledger(repo_dir)
                state_dir, _, binding = lifecycle.owned(repo_dir, session, loop, complete=True)
                lifecycle.prepared(state_dir, binding, required=True)
                lifecycle.observe(state_dir, "orders_rendered", binding, _view_digest(repo_dir, ledger))
        status(path, session)
        result["pending_teardown"] = False
        result["exit_code"] = 0
        result.pop("reason_code", None)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["reason_code"] = str(error) or "order_pending_teardown"
    return result
