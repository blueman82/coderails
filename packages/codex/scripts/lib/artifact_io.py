"""Typed JSON and atomic writes for workflow artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

JsonObject = dict[str, Any]


def read_object(path: str | Path) -> JsonObject:
    """Load a JSON object or raise on malformed input."""
    data: object = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return cast(JsonObject, data)


def write_bytes(path: str | Path, data: bytes) -> None:
    """Publish complete bytes through an unpublished sibling; failed writes leave the destination untouched."""
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


def write_object(path: str | Path, data: JsonObject) -> None:
    """Replace an object artifact with its existing indented UTF-8 JSON and terminal newline."""
    write_bytes(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def object_value(value: object) -> JsonObject:
    """Require and type a JSON object at a parsing boundary."""
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return cast(JsonObject, value)


def array_value(value: object) -> list[Any]:
    """Require and type a JSON array at a parsing boundary."""
    if not isinstance(value, list):
        raise ValueError("expected a JSON array")
    return cast(list[Any], cast(object, value))
