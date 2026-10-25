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


def write_object(path: str | Path, data: JsonObject) -> None:
    """Replace an artifact atomically using a temporary sibling."""
    destination = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=destination.name + ".", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


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
