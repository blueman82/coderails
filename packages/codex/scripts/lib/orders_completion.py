"""Join native graph completion to the durable standing-orders lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.lib import orders as order_cli  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.lib import orders_lifecycle as lifecycle  # noqa: E402
from scripts.lib.artifact_io import write_bytes  # noqa: E402
from scripts.lib.memory_adapter import MARKER  # noqa: E402

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


def _view_digest(repo_dir: Path, ledger: ol.Ledger, expected_views: object = None) -> str:
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
    if expected_views is not None and views != expected_views:
        raise ValueError("order_source_mismatch")
    return lifecycle.sha({"ledger": ledger, "views": views})


def _legacy_path(state_dir: Path, loop: str) -> Path:
    """Keep the explicit old-loop admission separate from progress and new-loop receipts."""
    return state_dir / f"orders-legacy-{hashlib.sha256(loop.encode()).hexdigest()}.json"


def _pending_path(state_dir: Path, loop: str) -> Path:
    """Keep the last render refusal bound to this completed loop."""
    return state_dir / f"orders-render-pending-{hashlib.sha256(loop.encode()).hexdigest()}.json"


def _pending_reason(state_dir: Path, binding: dict[str, Any], ledger: ol.Ledger) -> str:
    """Report a current render refusal only when its inputs still match."""
    path = _pending_path(state_dir, binding["loop_id"])
    if path.is_symlink():
        raise ValueError("order_wrong_session")
    if not path.exists():
        return ""
    try:
        row = lifecycle.object_file(path)
    except ValueError:
        return ""
    reason = row.get("reason_code")
    if row.get("binding") != binding or row.get("ledger_sha256") != lifecycle.sha(ledger):
        return ""
    return reason if isinstance(reason, str) and reason.strip() else ""


def _record_pending(state_dir: Path, binding: dict[str, Any], ledger: ol.Ledger, reason: str) -> None:
    """Save the actual render refusal without claiming a rendered view."""
    path = _pending_path(state_dir, binding["loop_id"])
    if path.is_symlink():
        raise ValueError("order_wrong_session")
    row = {"binding": binding, "ledger_sha256": lifecycle.sha(ledger), "reason_code": reason}
    write_bytes(path, (json.dumps(row, sort_keys=True) + "\n").encode())


def _d4_evidence(state_dir: Path, session: str, loop: str, ledger: ol.Ledger) -> bool:
    """Refuse an old-loop exception if any part of the new lifecycle has begun."""
    if lifecycle.preparation_path(state_dir, loop).exists() or (
        lifecycle.loop_key(session, loop) in ledger["ticked_loops"]
    ):
        return True
    if any(
        evidence.get("session_id") == session and evidence.get("loop_id") == loop
        for order in ledger["orders"]
        for evidence in order["evidence"]
    ):
        return True
    log = state_dir / "teardown.jsonl"
    if log.is_symlink():
        raise ValueError("order_wrong_session")
    if log.exists():
        try:
            rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
        except (OSError, ValueError) as error:
            raise ValueError("order_source_invalid") from error
        if any(not isinstance(row, dict) for row in rows):
            raise ValueError("order_source_invalid")
        if any(
            str(row.get("step", "")).startswith("orders_")
            and row.get("session_id") == session
            and row.get("loop_id") == loop
            for row in rows
        ):
            return True
    return False


def _legacy_admitted(path: Path, session: str, loop: str, ledger: ol.Ledger) -> bool:
    """Accept the reviewed graph source across completion-only bookkeeping updates."""
    receipt_path = _legacy_path(path.parent, loop)
    if receipt_path.is_symlink():
        raise ValueError("order_wrong_session")
    if not receipt_path.exists():
        return False
    state_dir, state, _ = lifecycle.owned(path.parent.parent, session, loop, complete=True)
    if _d4_evidence(state_dir, session, loop, ledger):
        raise ValueError("order_legacy_conflict")
    receipt = lifecycle.object_file(receipt_path)
    expected = {
        "schema": 1,
        "session_id": session,
        "loop_id": loop,
        "source_sha256": lifecycle.sha(lifecycle.source_state(state)),
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError("order_legacy_admission_stale")
    if not isinstance(receipt.get("progress_sha256"), str) or not re.fullmatch(
        r"[0-9a-f]{64}", receipt["progress_sha256"]
    ):
        raise ValueError("order_legacy_admission_stale")
    if not isinstance(receipt.get("reason"), str) or len(receipt["reason"].strip()) < 12:
        raise ValueError("order_legacy_admission_stale")
    return True


def admit_legacy(path: Path, session: str, loop: str, expected_sha256: str, reason: str) -> dict[str, Any]:
    """Record a reviewed pre-D4 completion without replaying age or changing progress."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256) or len(reason.strip()) < 12:
        raise ValueError("order_legacy_admission_invalid")
    with order_cli.locked(path.parent.parent):
        ledger = ol.open_ledger(path.parent.parent)
        state_dir, state, _ = lifecycle.owned(path.parent.parent, session, loop, complete=True)
        if _d4_evidence(state_dir, session, loop, ledger):
            raise ValueError("order_legacy_conflict")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected_sha256:
            raise ValueError("order_legacy_admission_stale")
        receipt = {
            "schema": 1,
            "session_id": session,
            "loop_id": loop,
            "progress_sha256": actual,
            "source_sha256": lifecycle.sha(lifecycle.source_state(state)),
            "reason": reason.strip(),
        }
        destination = _legacy_path(state_dir, loop)
        if destination.exists() or destination.is_symlink():
            if not _legacy_admitted(path, session, loop, ledger):
                raise ValueError("order_legacy_admission_stale")
            return {"legacy_admitted": True, "progress_sha256": actual}
        write_bytes(destination, (json.dumps(receipt, sort_keys=True) + "\n").encode())
        if hashlib.sha256(path.read_bytes()).hexdigest() != actual:
            raise ValueError("order_legacy_admission_stale")
    return {"legacy_admitted": True, "progress_sha256": actual}


def status(path: Path, session: str) -> None:
    """Refuse a complete loop whose tick or rendered views lack current bound receipts."""
    repo_dir = path.parent.parent
    source = lifecycle.object_file(path)
    loop = source.get("loop_id")
    if not isinstance(loop, str) or not loop.strip():
        raise ValueError("order_wrong_session")
    with order_cli.locked(repo_dir):
        ledger = ol.open_ledger(repo_dir)
        if _legacy_admitted(path, session, loop, ledger):
            return
        state_dir, state, binding = lifecycle.owned(repo_dir, session, loop, complete=True)
        if not lifecycle.preparation_path(state_dir, loop).exists():
            raise ValueError("order_legacy_admission_required")
        staged = lifecycle.prepared(state_dir, binding, required=True)
        digest = lifecycle.sha(staged)
        if lifecycle.loop_key(session, state["loop_id"]) not in ledger["ticked_loops"]:
            raise ValueError("order_pending_teardown")
        if not lifecycle.observe(state_dir, "orders_ticked", binding, digest, emit=False):
            raise ValueError("order_pending_teardown")
        try:
            rendered = _view_digest(repo_dir, ledger)
        except (OSError, ValueError) as error:
            raise ValueError(_pending_reason(state_dir, binding, ledger) or "order_pending_teardown") from error
        if not lifecycle.observe(state_dir, "orders_rendered", binding, rendered, emit=False):
            raise ValueError(_pending_reason(state_dir, binding, ledger) or "order_pending_teardown")


def finish(path: Path, session: str, loop: str) -> dict[str, Any]:
    """Resume idempotent tick and render after the native graph lock is released."""
    result: dict[str, Any] = {"pending_teardown": True, "exit_code": 3, "reason_code": "order_pending_teardown"}
    try:
        with order_cli.locked(path.parent.parent):
            ledger = ol.open_ledger(path.parent.parent)
            if _legacy_admitted(path, session, loop, ledger):
                return {"legacy_admitted": True, "pending_teardown": False, "exit_code": 0}
            if not lifecycle.preparation_path(path.parent, loop).exists():
                result["reason_code"] = "order_legacy_admission_required"
                return result
        tick_code, tick = _call(path, session, "tick", loop)
        result["tick"] = {"exit_code": tick_code, **tick}
        if tick_code not in (0, 3):
            result["reason_code"] = str(tick.get("reason_code") or "order_pending_teardown")
            return result
        render_code, render = _call(path, session, "render", loop)
        result["render"] = {"exit_code": render_code, **render}
        if render_code:
            reason = str(render.get("degraded") or render.get("reason_code") or "order_pending_teardown")
            result["reason_code"] = reason
            with order_cli.locked(path.parent.parent):
                ledger = ol.open_ledger(path.parent.parent)
                state_dir, _, binding = lifecycle.owned(path.parent.parent, session, loop, complete=True)
                _record_pending(state_dir, binding, ledger, reason)
            return result
        if render_code == 0:
            repo_dir = path.parent.parent
            with order_cli.locked(repo_dir):
                ledger = ol.open_ledger(repo_dir)
                if render.get("ledger_sha256") != lifecycle.sha(ledger):
                    raise ValueError("order_source_mismatch")
                state_dir, _, binding = lifecycle.owned(repo_dir, session, loop, complete=True)
                lifecycle.prepared(state_dir, binding, required=True)
                digest = _view_digest(repo_dir, ledger, render.get("view_sha256", {}))
                lifecycle.observe(state_dir, "orders_rendered", binding, digest)
        status(path, session)
        result["pending_teardown"] = False
        result["exit_code"] = 0
        result.pop("reason_code", None)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result["reason_code"] = str(error) or "order_pending_teardown"
    return result


def main(argv: list[str] | None = None) -> int:
    """Admit one reviewed old complete loop by exact saved progress hash."""
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("admit-legacy",))
    parser.add_argument("--dir", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--loop", required=True)
    parser.add_argument("--progress-sha256", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    try:
        output = admit_legacy(
            Path(args.dir) / args.session / "progress.json",
            args.session,
            args.loop,
            args.progress_sha256,
            args.reason,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"reason_code": str(error) or "order_state_error"}))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
