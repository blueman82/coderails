"""Validate every retained Note support through public selected-evidence reads."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from typing import Any, cast

from scripts.lib import memory_adapter as ma

EVIDENCE_ID = re.compile(r"E_[0-9a-f]{32}")
DIGEST = re.compile(r"[0-9a-f]{64}")
MAX_SUPPORTS = 100
MAX_OUTPUT_BYTES = 2 * 1024 * 1024


def seconds(value: object) -> bool:
    """Require finite nonnegative public timestamps without boolean coercion."""
    return type(value) in (int, float) and math.isfinite(cast("float", value)) and cast("float", value) >= 0


def object_value(value: object) -> dict[str, Any] | None:
    """Return an object without coercing malformed public output."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def objects(value: object) -> list[dict[str, Any]] | None:
    """Require a list of public objects, preserving an empty list."""
    if not isinstance(value, list):
        return None
    items = cast("list[object]", value)
    return [cast("dict[str, Any]", item) for item in items] if all(isinstance(item, dict) for item in items) else None


def read(argv: list[str], *, deadline: float | None = None) -> dict[str, Any] | ma.Degraded:
    """Bound parsed CLI output; transport timeout and refusal handling remain shared."""
    remaining = ma.TIMEOUT if deadline is None else min(ma.TIMEOUT, deadline - time.monotonic())
    if remaining <= 0:
        return ma.Degraded("learning_read_limit")
    output = ma.run_cli(argv, timeout=remaining)
    if isinstance(output, ma.Degraded):
        return output
    if len(output.encode()) > MAX_OUTPUT_BYTES:
        return ma.Degraded("learning_read_limit")
    try:
        value: object = json.loads(output)
    except ValueError:
        return ma.Degraded("muninn_bad_output")
    return object_value(value) or ma.Degraded("muninn_bad_output")


def evidence_ids(value: object) -> list[str] | None:
    """Require unique explicit evidence IDs instead of an inferred selection."""
    if not isinstance(value, list):
        return None
    values = cast("list[object]", value)
    if not values or len(values) > MAX_SUPPORTS:
        return None
    if any(not isinstance(item, str) or EVIDENCE_ID.fullmatch(item) is None for item in values):
        return None
    ids = cast("list[str]", values)
    return ids if len(set(ids)) == len(ids) else None


def _selector(value: dict[str, Any]) -> bool:
    required = {
        "id",
        "provider",
        "thread_id",
        "session_root",
        "line",
        "part",
        "line_sha256",
        "source_version",
        "projection_version",
        "original_locator",
        "selector",
        "selector_digest",
        "evidence_type",
        "authority",
        "scope",
        "excerpt",
        "state",
        "selected_at",
    }
    if not required <= value.keys() or not seconds(value.get("selected_at")):
        return False
    original = object_value(value.get("original_locator"))
    if original is None:
        return False
    if original.get("kind") == "jsonl":
        if (
            not isinstance(original.get("path"), str)
            or not original["path"]
            or type(original.get("byte_offset")) is not int
            or original["byte_offset"] < 0
            or type(original.get("byte_length")) is not int
            or original["byte_length"] < 1
        ):
            return False
    elif original.get("kind") != "cursor_db" or any(
        not isinstance(original.get(key), str) or not original[key]
        for key in ("database", "conversation_id", "record_key")
    ):
        return False
    selected = object_value(value.get("selector"))
    if selected is None or set(selected) != {"json_pointer", "start", "end"}:
        return False
    pointer, start, end = (selected[key] for key in ("json_pointer", "start", "end"))
    if not isinstance(pointer, str) or pointer and not pointer.startswith("/"):
        return False
    if any("~" in part.replace("~0", "").replace("~1", "") for part in pointer.split("/")[1:]):
        return False
    if not (start is None and end is None or type(start) is int and type(end) is int and 0 <= start <= end):
        return False
    digest = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    return value.get("selector_digest") == digest.hexdigest() and all(
        isinstance(value.get(key), str) and value[key].strip() for key in ("source_version", "projection_version")
    )


def _binding(evidence: dict[str, Any], source: dict[str, Any], scope: dict[str, Any], window: dict[str, Any]) -> bool:
    evidence_scope = object_value(evidence.get("scope"))
    admitted = object_value(window.get("source"))
    provider, thread, line, part = (evidence.get(key) for key in ("provider", "thread_id", "line", "part"))
    if evidence_scope is None or admitted is None or type(line) is not int or type(part) is not int:
        return False
    return (
        evidence_scope.get("project_id") == scope.get("project_id")
        and evidence_scope.get("task") in (None, scope.get("task"))
        and (provider, thread) == (admitted.get("provider"), admitted.get("thread_id"))
        and window["from_line"] <= line <= window["through_line"]
        and part >= 1
        and source.get("ref") == f"{provider}:{thread}:{line}.{part}"
        and isinstance(evidence.get("line_sha256"), str)
        and DIGEST.fullmatch(evidence["line_sha256"]) is not None
        and source.get("line_sha256") == evidence["line_sha256"]
    )


def _physical(evidence: dict[str, Any], source: dict[str, Any], deadline: float | None) -> ma.Degraded | None:
    ref, quote = source["ref"], evidence["excerpt"]
    opened = read(["open", ref, "--context", "0"], deadline=deadline)
    if isinstance(opened, ma.Degraded):
        return opened
    provenance = object_value(opened.get("provenance"))
    if opened.get("hash_ok") is not True:
        return ma.Degraded(
            "learning_source_changed" if opened.get("hash_ok") is False else "learning_source_unavailable"
        )
    if (
        provenance is None
        or opened.get("ref") != ref
        or any(
            provenance.get(public) != evidence.get(retained)
            for public, retained in (
                ("provider", "provider"),
                ("thread", "thread_id"),
                ("session", "session_root"),
                ("line", "line"),
                ("part", "part"),
                ("line_sha256", "line_sha256"),
            )
        )
    ):
        return ma.Degraded("learning_source_changed")
    if (
        opened.get("answer_citable") is not True
        or any(opened.get(key) is not False for key in ("redacted", "flagged", "truncated"))
        or provenance.get("source_status") != "active"
        or provenance.get("class", "primary") != "primary"
        or provenance.get("parent_event_id") is not None
        or (provenance.get("role"), provenance.get("kind")) != ("user", "prompt")
    ):
        return ma.Degraded("learning_source_authority")
    checked = read(["quote-check", ref, quote], deadline=deadline)
    if isinstance(checked, ma.Degraded):
        return checked
    return None if checked.get("match") is True and "error" not in checked else ma.Degraded("learning_quote_mismatch")


def validate(
    refs: list[str],
    sources_value: object,
    evidence_value: object,
    scope: dict[str, Any],
    window: dict[str, Any],
    *,
    deadline: float | None = None,
) -> list[dict[str, Any]] | ma.Degraded:
    """Join each exact E-id/ref/hash/selection, then check every live physical user prompt."""
    sources, evidence = objects(sources_value), objects(evidence_value)
    if sources is None or evidence is None:
        return ma.Degraded("learning_selection_unavailable")
    if len(sources) > MAX_SUPPORTS or len(evidence) > MAX_SUPPORTS:
        return ma.Degraded("learning_read_limit")
    result: list[dict[str, Any]] = []
    for ident in refs:
        retained = [item for item in sources if item.get("evidence_id") == ident]
        selected = [item for item in evidence if item.get("id") == ident]
        if len(retained) != 1 or len(selected) != 1:
            return ma.Degraded("learning_selection_unavailable")
        source, chosen = retained[0], selected[0]
        if not _binding(chosen, source, scope, window) or not _selector(chosen):
            return ma.Degraded("learning_evidence_mismatch")
        if chosen.get("state") != "live":
            return ma.Degraded("learning_source_unavailable")
        if (chosen.get("authority"), chosen.get("evidence_type")) != ("direct_owner", "owner_statement"):
            return ma.Degraded("learning_source_authority")
        if not isinstance(chosen.get("excerpt"), str) or not chosen["excerpt"].strip():
            return ma.Degraded("learning_selection_unavailable")
        failure = _physical(chosen, source, deadline)
        if failure is not None:
            return failure
        result.append({**chosen, "ref": source["ref"], "quote": chosen["excerpt"]})
    return result
