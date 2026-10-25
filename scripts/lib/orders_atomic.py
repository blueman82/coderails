"""Atomic byte publication for standing-order artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_bytes(path: str | Path, data: bytes) -> None:
    """Publish complete bytes through an unpublished sibling."""
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            remaining = memoryview(data)
            while remaining:
                written = os.write(stream.fileno(), remaining)
                if written <= 0:
                    raise OSError("incomplete artifact write")
                remaining = remaining[written:]
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
