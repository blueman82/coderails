"""Session lock for an atomic merge-budget check and execution claim."""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Generator
from contextlib import contextmanager

from scripts.lib.authority_object import authority_path


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
