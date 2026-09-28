"""Read typed native graph evidence data without mutating it."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from graph_identity import GraphError
from json_types import JsonValue


def object_value(value: object, label: str) -> dict[str, Any]:
    """Require a JSON object."""
    if not isinstance(value, dict):
        raise GraphError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def array_value(value: object, label: str) -> list[JsonValue]:
    """Require a JSON array."""
    if not isinstance(value, list):
        raise GraphError(f"{label} must be an array")
    return cast(list[JsonValue], value)


def nonempty(value: object, label: str) -> str:
    """Require a nonblank string."""
    if not isinstance(value, str) or not value.strip():
        raise GraphError(f"{label} must be a non-empty string")
    return value


def load_evidence(path: Path, label: str) -> dict[str, Any]:
    """Load a named JSON evidence object."""
    try:
        with path.open(encoding="utf-8") as handle:
            parsed: JsonValue = cast(JsonValue, json.load(handle))
            return object_value(cast(object, parsed), label)
    except (OSError, json.JSONDecodeError) as error:
        raise GraphError(f"{label} is missing or invalid: {error}") from error


def read_records(path: Path, label: str) -> list[tuple[int, dict[str, Any]]]:
    """Read numbered native transcript records."""
    records: list[tuple[int, dict[str, Any]]] = []
    try:
        with path.open(encoding="utf-8") as transcript:
            for line_number, line in enumerate(transcript, 1):
                record: JsonValue = cast(JsonValue, json.loads(line))
                records.append((line_number, object_value(cast(object, record), f"{label} line {line_number}")))
    except (OSError, json.JSONDecodeError) as error:
        raise GraphError(f"{label} is missing or invalid: {error}") from error
    if not records:
        raise GraphError(f"{label} is empty")
    return records


def event_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Extract a native transcript event payload."""
    payload = record.get("payload", record)
    return cast(dict[str, Any], payload) if isinstance(payload, dict) else {}
