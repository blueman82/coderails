"""Session lock for an atomic merge-budget check and execution claim."""

from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from scripts.lib.authority_object import authority_path


def reservations(session: str, base: Path | None = None) -> int:
    """Count pending and completed advisory merge claims in the session."""
    auth = authority_path(session, base)
    return len(list((auth.parent / "merges").glob("*.json"))) if auth else 0


def reserve(session: str, number: str, bind: dict[str, str]) -> Path | None:
    """Claim one PR and head under the caller's session lock; None means the claim failed."""
    auth = authority_path(session)
    if auth is None or not number.isdigit() or not all(bind.get(k) for k in ("repository", "ref", "sha")):
        return None
    directory = auth.parent / "merges"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid.uuid4().hex}.json"
        with path.open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "pr": number,
                    "repository": bind["repository"],
                    "ref": bind["ref"],
                    "head": bind["sha"],
                    "state": "pending",
                },
                stream,
            )
        return path
    except OSError:
        return None


def settle(path: Path, success: bool) -> None:
    """Keep a successful claim in the ledger; release one confirmed failed attempt."""
    if success:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["state"] = "completed"
        path.write_text(json.dumps(data), encoding="utf-8")
    else:
        path.unlink()


@contextmanager
def lock(session: str) -> Generator[bool, None, None]:
    """Bound the wait and fail closed when the session lock cannot be acquired."""
    auth = authority_path(session)
    if auth is None:
        yield False
        return
    try:
        auth.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(auth.parent / "merge-budget.lock", os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield False
        return
    acquired = False
    try:
        deadline = time.monotonic() + 5.0
        while not acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
            except OSError:
                break
        yield acquired
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
