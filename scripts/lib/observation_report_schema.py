"""Closed metadata checks for the source-bound observation report."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, NoReturn, cast

KINDS = ("invocation", "read", "failed_read", "mention", "uncertain")
HEX = re.compile(r"^[0-9a-f]{64}$")
EVENT_FILE = re.compile(r"^events\.([0-9a-f]{64})\.jsonl$")
FINGERPRINT = re.compile(r"^sha256:([0-9a-f]{64});identity:.+$")
EVENT_KEYS = {
    "schemaVersion",
    "eventId",
    "traceId",
    "spanId",
    "parentSpanId",
    "name",
    "kind",
    "status",
    "startTimeUnixNano",
    "endTimeUnixNano",
    "events",
    "attributes",
    "provenance",
}
ATTRIBUTE_KEYS = {
    "tool.name",
    "gen_ai.operation.name",
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "gen_ai.usage.cache_read_input_tokens",
    "gen_ai.usage.cache_creation_input_tokens",
    "coderails.usage.semantics",
    "coderails.usage.identity_sha256",
    "coderails.source.ordinal",
    "coderails.source.item",
    "coderails.actor.kind",
    "coderails.actor.id",
    "coderails.loop.id",
    "coderails.graph.revision",
    "coderails.wave.id",
    "coderails.node.id",
    "coderails.node.name",
    "coderails.node.lane_code",
    "coderails.attempt",
    "coderails.native.call_id",
    "coderails.child.id",
    "coderails.duration_ms",
    "coderails.duration.basis",
    "coderails.start_time.basis",
    "coderails.start_time.method",
    "coderails.start_time.source_refs",
    "coderails.end_time.basis",
    "coderails.end_time.method",
    "coderails.end_time.source_refs",
    "coderails.time.basis",
    "coderails.time.method",
    "coderails.time.source_refs",
    "coderails.elapsed_gap_ms",
    "coderails.elapsed_gap.basis",
    "coderails.elapsed_gap.method",
    "coderails.elapsed_gap.cause",
    "coderails.elapsed_gap.start_source_ref",
    "coderails.elapsed_gap.end_source_ref",
    "coderails.parent_join.basis",
    "coderails.parent_join.method",
    "coderails.parent_join.parent_source_ref",
    "coderails.parent_join.child_source_ref",
    "coderails.file.change_count",
    "coderails.evidence.kind",
    "coderails.evidence.id",
    "coderails.observation.kind",
    "coderails.observation.target_kind",
    "coderails.observation.target_sha256",
    "coderails.observation.bytes",
}


class ReportError(ValueError):
    """An input cannot support a source-bound report."""


def require(ok: bool, message: str) -> None:
    """Refuse a bad input without printing any source content."""
    if not ok:
        raise ReportError(message)


def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON duplicate keys can hide a changed binding."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in out, "duplicate JSON field")
        out[key] = value
    return out


def reject_constant(_value: str) -> NoReturn:
    """JSON NaN and Infinity are not source metadata."""
    raise ReportError("nonfinite JSON value")


def parse_json(data: bytes) -> object:
    """Read one UTF-8 JSON value with duplicate-key rejection."""
    try:
        return cast(
            object, json.loads(data.decode("utf-8"), object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ReportError("malformed UTF-8 JSON") from error


def sha(data: bytes) -> str:
    """Return a lowercase SHA-256 digest."""
    return hashlib.sha256(data).hexdigest()


def bound_file(path: object, expected: object, base: Path, label: str) -> tuple[Path, bytes]:
    """Read and rehash an explicit local input."""
    if not isinstance(path, str) or not path:
        raise ReportError(f"missing {label} path")
    if not isinstance(expected, str) or HEX.fullmatch(expected) is None:
        raise ReportError(f"invalid {label} hash")
    file = Path(path)
    if not file.is_absolute():
        file = base / file
    try:
        data = file.read_bytes()
    except OSError as error:
        raise ReportError(f"{label} unavailable") from error
    require(sha(data) == expected, f"{label} hash mismatch")
    return file.resolve(), data


def named(value: object, label: str) -> str:
    """Read a nonempty identity value."""
    if not isinstance(value, str) or not value:
        raise ReportError(f"invalid {label}")
    return value


def object_keys(value: object, keys: set[str], label: str) -> dict[str, Any]:
    """Check a closed JSON object."""
    data = mapping(value, label)
    require(set(data) == keys, f"invalid {label} fields")
    return data


def mapping(value: object, label: str) -> dict[str, Any]:
    """Narrow one JSON object after a runtime shape check."""
    if not isinstance(value, dict):
        raise ReportError(f"invalid {label} fields")
    return cast(dict[str, Any], value)


def sequence(value: object, label: str) -> list[Any]:
    """Narrow one JSON array after a runtime shape check."""
    if not isinstance(value, list):
        raise ReportError(f"invalid {label} list")
    return cast(list[Any], value)  # type: ignore[redundant-cast]


def check_attributes(attrs: object) -> dict[str, Any]:
    """Reject unapproved metadata and count only typed observations."""
    attrs = mapping(attrs, "event attributes")
    require(set(attrs) <= ATTRIBUTE_KEYS, "event attributes are not metadata")
    require(
        all(
            value is None
            or isinstance(value, (str, bool))
            or (isinstance(value, (int, float)) and math.isfinite(value))
            for value in attrs.values()
        ),
        "invalid event attribute value",
    )
    kind = attrs.get("coderails.observation.kind")
    if kind is not None:
        require(
            kind in KINDS and attrs.get("coderails.observation.target_kind") in ("skill", "context"),
            "invalid observation kind",
        )
        target = attrs.get("coderails.observation.target_sha256")
        require(isinstance(target, str) and HEX.fullmatch(target) is not None, "invalid observation target")
        size = attrs.get("coderails.observation.bytes")
        require(size is None or (type(size) is int and size >= 0), "invalid observation byte count")
        if kind in ("read", "failed_read"):
            named(attrs.get("coderails.native.call_id"), "read call ID")
    else:
        require(not any(key.startswith("coderails.observation.") for key in attrs), "partial observation")
    semantics = attrs.get("coderails.usage.semantics")
    require(semantics is None or semantics in ("cumulative", "incremental"), "invalid usage semantics")
    identity = attrs.get("coderails.usage.identity_sha256")
    if "coderails.usage.identity_sha256" in attrs:
        require(
            semantics == "incremental" and isinstance(identity, str) and HEX.fullmatch(identity) is not None,
            "invalid usage identity",
        )
    for key in ("gen_ai.usage.cache_read_input_tokens", "gen_ai.usage.cache_creation_input_tokens"):
        number = attrs.get(key)
        require(number is None or (type(number) is int and number >= 0), "invalid cache usage")
    return attrs


def check_event(
    value: object, session: dict[str, Any], source_ids: set[str]
) -> tuple[str, str | None, bool, str, str | None]:
    """Validate one metadata event and return only fields needed for counts."""
    event = object_keys(value, EVENT_KEYS, "event")
    require(
        type(event["schemaVersion"]) is int
        and event["schemaVersion"] == 1
        and all(isinstance(event[key], str) and event[key] for key in ("eventId", "traceId", "spanId", "name", "kind")),
        "invalid event identity",
    )
    expected_trace = sha(f"{session['provider']}:{session['native_session_id']}".encode())[:32]
    require(event["traceId"] == expected_trace, "foreign trace identity")
    require(event["parentSpanId"] is None or isinstance(event["parentSpanId"], str), "invalid parent span")
    require(event["parentSpanId"] != event["spanId"], "self parent span")
    require(event["kind"] in ("internal", "client", "server", "producer", "consumer"), "invalid event kind")
    for field in ("startTimeUnixNano", "endTimeUnixNano"):
        time = event[field]
        require(time is None or (isinstance(time, str) and time.isdecimal()), "invalid event time")
    status = mapping(event["status"], "status")
    require(set(status) <= {"value", "basis", "derivation"}, "invalid event status")
    require(
        status.get("value") in ("unset", "ok", "error", "unavailable")
        and status.get("basis") in ("source", "observed", "derived", "unavailable"),
        "invalid event status",
    )
    for raw in sequence(event["events"], "span events"):
        item = object_keys(raw, {"name", "timeUnixNano", "attributes"}, "span event")
        span_time = item["timeUnixNano"]
        require(
            isinstance(item["name"], str)
            and (span_time is None or (isinstance(span_time, str) and span_time.isdecimal())),
            "invalid span event",
        )
        check_attributes(item["attributes"])
    attrs = check_attributes(event["attributes"])
    provenance = mapping(event["provenance"], "provenance")
    require(
        set(provenance)
        <= {"provider", "nativeSessionId", "sourceId", "sourceOrdinal", "basis", "sourceRef", "derivation"},
        "invalid provenance fields",
    )
    require(
        provenance.get("provider") == session["provider"]
        and provenance.get("nativeSessionId") == session["native_session_id"]
        and provenance.get("sourceId") in source_ids,
        "foreign event",
    )
    require(provenance.get("basis") in ("source", "observed", "derived", "unavailable"), "invalid provenance basis")
    ordinal = provenance.get("sourceOrdinal")
    source_ref = object_keys(provenance.get("sourceRef"), {"kind", "recordId", "ordinal"}, "source reference")
    require(
        type(ordinal) is int
        and ordinal >= 0
        and source_ref["ordinal"] == ordinal
        and isinstance(source_ref["recordId"], str),
        "invalid source reference",
    )
    source_id, record_id = provenance["sourceId"], source_ref["recordId"]
    kind = source_ref["kind"]
    if kind in ("claude_parent_record", "claude_child_record"):
        prefix = f"{source_id}:{ordinal}"
        valid = re.fullmatch(re.escape(prefix) + r"(?:\:item\:\d+)?", record_id) is not None
    elif kind in ("codex_parent_record", "codex_child_record"):
        valid = record_id == f"{source_id}:{ordinal}"
    elif kind in ("claude_graph_record", "codex_graph_record"):
        valid = record_id.startswith(f"{Path(source_id).name}#")
    elif kind in ("claude_hook_audit_record", "codex_hook_audit_record"):
        valid = record_id == f"audit:{ordinal}"
    else:
        valid = False
    require(valid and kind.startswith(f"{session['provider']}_"), "foreign source reference")
    usage = any(key.startswith("gen_ai.usage.") for key in attrs)
    return event["eventId"], attrs.get("coderails.observation.kind"), usage, event["spanId"], event["parentSpanId"]
