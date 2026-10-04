"""Stdlib-only mkdir lock that recovers from a dead owner without stealing from a live one.

The lock is a directory holding an `owner` file {pid, host, start, ts}. A lock is stolen only when its owner is
provably dead on THIS host (pid gone, or pid alive with a different start time = reused; a pid recorded by
another host is never judged) or when the owner file is
absent/torn AND the directory is older than a bound. Stealing is an atomic rename of the directory, then a
recheck that the renamed owner is the one we judged. Known ceiling: if a new holder wins between judge and
rename and a third process takes the vacated name before our rename-back, two holders can briefly coexist.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

STALE_AFTER_S = 60.0
HOST = socket.gethostname()
EVENTS_FILE = "lock-events.jsonl"


@lru_cache(maxsize=64)
def process_start(pid: int) -> str:
    """Return `ps -o lstart=` for pid, or '' when unavailable (cached: one fork per pid per process)."""
    try:
        done = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return " ".join(done.stdout.split())


def emit(lock: Path, reason: str, owner_pid: int | None = None) -> None:
    """Append one fail-open, non-authoritative lock event beside the lock."""
    row = {
        "lock": str(lock),
        "owner_pid": owner_pid,
        "pid": os.getpid(),
        "ts": time.time(),
        "event_id": str(uuid.uuid4()),
        "reason": reason,
        "schema": "lock_event",
        "non_authoritative": True,
    }
    with suppress(OSError), (lock.parent / EVENTS_FILE).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def read_owner(lock: Path) -> str | None:
    """Return the raw owner text, or None when absent or unreadable."""
    try:
        return (lock / "owner").read_text(encoding="utf-8")
    except OSError:
        return None


def parse_owner(raw: str | None) -> dict[str, Any] | None:
    """Return the owner object when it names a positive integer pid, else None (torn, empty, foreign)."""
    try:
        value: Any = json.loads(raw or "")
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    owner = cast(dict[str, Any], value)
    pid = owner.get("pid")
    return owner if isinstance(pid, int) and pid > 0 else None


def owner_is_dead(owner: dict[str, Any]) -> bool:
    """True only when the pid is gone or has been reused; EPERM and any doubt mean alive."""
    pid = cast(int, owner["pid"])
    if pid == os.getpid() or owner.get("host", HOST) != HOST:  # another host's pid is not ours to judge
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    recorded = str(owner.get("start") or "")
    current = process_start(pid) if recorded else ""
    return bool(recorded and current and recorded != current)


def stale_reason(lock: Path, raw: str | None) -> str | None:
    """Return the steal reason code for this lock, or None when it must be treated as held."""
    owner = parse_owner(raw)
    if owner is not None and owner_is_dead(owner):
        return "lock_stolen_dead_owner"
    if owner is not None and owner.get("host", HOST) == HOST:
        return None  # live local owner: age alone never steals
    try:
        age = time.time() - lock.stat().st_mtime
    except OSError:
        return None
    try:
        bound = float(os.environ.get("CLAUDE_LOCK_STALE_S", STALE_AFTER_S))
    except ValueError:
        bound = STALE_AFTER_S  # fail-open: a malformed knob must not change the lock result
    return "lock_stolen_age" if age > bound else None  # negative age (clock skew) is never old


def steal(lock: Path, judged: str | None) -> bool:
    """Atomically move the stale lock aside; True only if we removed exactly the lock we judged."""
    aside = Path(f"{lock}.stale.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        os.rename(lock, aside)
    except OSError:
        return False  # another stealer (or the owner's release) won the rename
    if read_owner(aside) != judged:
        with suppress(OSError):
            os.rename(aside, lock)  # a new holder won between judge and rename; give it back
        return False
    shutil.rmtree(aside, ignore_errors=True)
    return True


def try_create(lock: Path) -> bool:
    """Create the lock directory and record ownership; undo the mkdir if ownership cannot be recorded."""
    try:
        lock.mkdir()
    except OSError:
        return False
    if write_owner(lock):
        return True
    shutil.rmtree(lock, ignore_errors=True)
    return False


def acquire_dir_lock(lock: Path, attempts: int = 5, delay: float = 0.3) -> tuple[bool, str]:
    """Take the lock, stealing it if stale.

    Returns (acquired, reason), reason in acquired | lock_stolen_dead_owner | lock_stolen_age | lock_busy.
    """
    reason = "acquired"
    for attempt in range(attempts):
        if try_create(lock):
            return True, reason
        judged = read_owner(lock)
        why = stale_reason(lock, judged) if lock.is_dir() else None
        if why and steal(lock, judged):
            reason = why
            owner = parse_owner(judged)
            emit(lock, why, owner["pid"] if owner else None)
            if try_create(lock):  # no sleep after a steal
                return True, reason
        if attempt + 1 < attempts:
            time.sleep(delay)
    owner = parse_owner(read_owner(lock))
    emit(lock, "lock_busy", owner["pid"] if owner else None)
    return False, "lock_busy"


def write_owner(lock: Path) -> bool:
    """Record this process as owner via tmp + os.replace inside the lock dir."""
    body = json.dumps({"pid": os.getpid(), "host": HOST, "start": process_start(os.getpid()), "ts": time.time()})
    tmp = lock / f"owner.tmp.{os.getpid()}"
    try:
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, lock / "owner")
    except OSError:
        return False
    return True


def release_dir_lock(lock: Path) -> bool:
    """Remove the lock only if we still own it; never remove a lock someone else now holds."""
    owner = parse_owner(read_owner(lock))
    if owner is None or owner["pid"] != os.getpid():
        return False
    with suppress(OSError):
        (lock / "owner").unlink()
    try:
        lock.rmdir()
    except OSError:
        return False
    return True
