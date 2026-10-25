"""Versioned progress.json conversion shared by both providers; materialized byte-for-byte.

Pure: `convert` maps one parsed state to the current minor or refuses with a closed code. It never guesses: any state
whose meaning is not certain is refused and the provider CLI leaves the file untouched.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import graph_contract

STATE_MINOR = 3
CODES = (
    "state_not_object",
    "unknown_schema",
    "minor_invalid",
    "minor_future",
    "foreign_session",
    "graph_not_object",
    "malformed_stops",
    "malformed_work_units",
    "active_wave_ambiguous",
    "active_wave_in_flight",
    "backup_exists",
    "invalid_result",
)
BACKUP_SUFFIX = ".pre-convert"


class ConvertRefusedError(ValueError):
    """A deterministic refusal; `code` is one of CODES and the trace reason is convert_refused_<code>."""

    def __init__(self, code: str, message: str) -> None:
        """Keep the closed code beside the human message."""
        super().__init__(f"{code}: {message}")
        self.code = code


def _graph(state: dict[str, Any]) -> dict[str, Any]:
    graph = state.get("graph")
    if not isinstance(graph, dict):
        raise ConvertRefusedError("graph_not_object", "graph must be an object")
    return cast(dict[str, Any], graph)


def _check_active_wave(graph: dict[str, Any]) -> None:
    """Never accept an in-flight wave without its recorded history, even at the current minor version."""
    history = graph.get("wave_history", {})
    active = graph.get("active_wave")
    if not isinstance(history, dict):
        raise ConvertRefusedError("active_wave_ambiguous", "wave_history must be an object")
    wave_id = cast(dict[str, Any], active).get("wave_id") if isinstance(active, dict) else None
    if active is not None and (not isinstance(wave_id, str) or wave_id not in history):
        raise ConvertRefusedError(
            "active_wave_ambiguous", "a wave is in flight with no wave_history entry: record or recover it first"
        )


def _v0_to_v1(state: dict[str, Any]) -> None:
    """Add the typed containers v1 readers rely on."""
    graph = _graph(state)
    graph.setdefault("wave_history", {})
    state.setdefault("stops", [])
    if not isinstance(state["stops"], list):
        raise ConvertRefusedError("malformed_stops", "stops must be an array")
    if "updated_at" not in state and isinstance(state.get("created"), str):
        state["updated_at"] = state["created"]


def _v1_to_v2(state: dict[str, Any]) -> None:
    """Add dispatch records: waves from this revision on must carry a begin-wave envelope. Refuse an open wave."""
    graph = _graph(state)
    if graph.get("active_wave") is not None:
        raise ConvertRefusedError(
            "active_wave_in_flight", "a wave is in flight and its v1 dispatches are ambiguous: finish or recover it"
        )
    revision = state.get("revision")
    if type(revision) is not int or revision < 1:
        raise ConvertRefusedError("invalid_result", "revision must be a positive integer")
    graph.setdefault("dispatches", {})
    graph.setdefault("contract_from_revision", revision)


def _v2_to_v3(state: dict[str, Any]) -> None:
    """Start required-context contracts at this revision; never convert an open or torn v2 wave."""
    graph = _graph(state)
    if graph.get("active_wave") is not None:
        raise ConvertRefusedError(
            "active_wave_in_flight", "finish or recover the v2 wave before required-context conversion"
        )
    revision, start = state.get("revision"), graph.get("contract_from_revision")
    dispatches = graph.get("dispatches")
    if (
        type(revision) is not int
        or type(start) is not int
        or not 1 <= start <= revision
        or not isinstance(dispatches, dict)
    ):
        raise ConvertRefusedError("invalid_result", "v2 dispatch records or cutoff are invalid")
    for identifier, raw_row in cast(dict[object, object], dispatches).items():
        if not isinstance(identifier, str) or not isinstance(raw_row, dict):
            raise ConvertRefusedError("invalid_result", "v2 dispatch record is incomplete")
        row = cast(dict[str, Any], raw_row)
        if (
            not all(isinstance(row.get(key), str) and row[key] for key in ("node_id", "wave_id"))
            or type(row.get("revision")) is not int
            or not start <= row["revision"] < revision
            or type(row.get("attempt")) is not int
            or row["attempt"] < 1
            or row.get("envelope_version") != graph_contract.ENVELOPE_VERSION
        ):
            raise ConvertRefusedError("invalid_result", "v2 dispatch record is incomplete")
        try:
            contract = graph_contract.validate_contract(row.get("contract"))
            digest = graph_contract.sections_sha256(contract)
        except (TypeError, ValueError) as error:
            raise ConvertRefusedError("invalid_result", "v2 dispatch contract is invalid") from error
        if row.get("prompt_sections_sha256") != digest:
            raise ConvertRefusedError("invalid_result", "v2 dispatch contract digest is invalid")
    graph["context_from_revision"] = revision


CONVERSIONS: tuple[tuple[int, Callable[[dict[str, Any]], None]], ...] = ((0, _v0_to_v1), (1, _v1_to_v2), (2, _v2_to_v3))


def convert(state: object, session: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (converted copy, report); the input is never mutated and a current state is returned unchanged."""
    if not isinstance(state, dict):
        raise ConvertRefusedError("state_not_object", "state must be an object")
    source = cast(dict[str, Any], state)
    if source.get("schema_version") != 3:
        raise ConvertRefusedError("unknown_schema", f"unknown schema_version {source.get('schema_version')!r}")
    if session is not None and source.get("session_id") != session:
        raise ConvertRefusedError("foreign_session", "session does not own this state")
    minor = source.get("state_minor", 0)
    if type(minor) is not int or minor < 0:
        raise ConvertRefusedError("minor_invalid", "state_minor must be a non-negative integer")
    if minor > STATE_MINOR:
        raise ConvertRefusedError("minor_future", f"state_minor {minor} is newer than this tool ({STATE_MINOR})")
    if minor == STATE_MINOR:
        try:
            graph_contract.validate_dispatch_state(source)
        except graph_contract.DispatchDeniedError as error:
            raise ConvertRefusedError(error.code, str(error)) from error
    _check_active_wave(_graph(source))
    stops, units = source.get("stops", []), source.get("work_units", {})
    if not isinstance(stops, list) or not all(isinstance(row, dict) for row in cast(list[object], stops)):
        raise ConvertRefusedError("malformed_stops", "stops must be an array of objects")
    if not isinstance(units, dict):
        raise ConvertRefusedError("malformed_work_units", "work_units must be an object")
    result = copy.deepcopy(source)
    steps = [f"v{at}->v{at + 1}" for at, _ in CONVERSIONS if at >= minor]
    for at, step in CONVERSIONS:
        if at >= minor:
            step(result)
    if steps:
        result["state_minor"] = STATE_MINOR
    return result, {"from": minor, "to": STATE_MINOR, "changed": bool(steps), "steps": steps}


def write_backup(path: Path) -> Path:
    """Exclusively create <path>.pre-convert holding the original bytes; refuse if it exists, never delete."""
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    try:
        with backup.open("xb") as stream:
            stream.write(path.read_bytes())
    except FileExistsError as error:
        raise ConvertRefusedError("backup_exists", f"{backup.name} already exists: inspect it first") from error
    return backup
