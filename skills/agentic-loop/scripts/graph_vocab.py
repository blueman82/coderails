"""Closed stop vocabulary shared by both providers; materialized byte-for-byte, never redefined locally."""

from __future__ import annotations

from typing import Any, cast

STOP_CATEGORIES = ("hard-stop", "approval-gate", "awaiting-input", "complete")
STOP_REASON_CODES = (
    "work_complete",
    "needs_human_input",
    "needs_approval",
    "node_hard_stop",
    "environment_blocked",
    "other",
)
DISPOSITION_KINDS = ("clean-break", "preserve-compat")


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def disposition_problem(kind: object, named_blocker: object, removal_ticket: object) -> str | None:
    """None when the triple is legal, else why not: preserve-compat needs both non-blank, clean-break neither."""
    if kind not in DISPOSITION_KINDS:
        return f"disposition kind must be one of {DISPOSITION_KINDS}"
    if kind == "preserve-compat" and not (_filled(named_blocker) and _filled(removal_ticket)):
        return "preserve-compat requires a non-blank named blocker and removal ticket"
    if kind == "clean-break" and (named_blocker is not None or removal_ticket is not None):
        return "clean-break forbids a named blocker and a removal ticket"
    return None


def validate_disposition(
    kind: str | None, named_blocker: str | None, removal_ticket: str | None
) -> dict[str, str] | None:
    """The object `add-unit` stores on work_units[u].disposition; None when no disposition flag was given."""
    if kind is None:
        if named_blocker is not None or removal_ticket is not None:
            raise ValueError("--named-blocker and --removal-ticket need --disposition")
        return None
    problem = disposition_problem(kind, named_blocker, removal_ticket)
    if problem:
        raise ValueError(problem)
    given = {"kind": kind, "named_blocker": named_blocker, "removal_ticket": removal_ticket}
    return {key: value.strip() for key, value in given.items() if value is not None}


def _stored(units: object) -> dict[str, object]:
    """Each unit id mapped to its raw stored disposition (None when the unit has none)."""
    if not isinstance(units, dict):
        return {}
    found: dict[str, object] = {}
    for identifier, unit in cast(dict[object, object], units).items():
        found[str(identifier)] = cast(dict[str, object], unit).get("disposition") if isinstance(unit, dict) else None
    return found


def disposition_offenders(units: object) -> list[str]:
    """Unit ids whose stored disposition is illegal (defence against hand-edited state); units without one pass."""
    found: list[str] = []
    for identifier, stored in _stored(units).items():
        if stored is None:
            continue
        fields = cast(dict[str, object], stored) if isinstance(stored, dict) else {}
        if not fields or disposition_problem(
            fields.get("kind"), fields.get("named_blocker"), fields.get("removal_ticket")
        ):
            found.append(identifier)
    return found


def disposition_report(units: object) -> dict[str, Any]:
    """The `disposition-audit` output: every unit's disposition kind (None when unset) and the offenders."""
    kinds = {
        identifier: cast(dict[str, object], stored).get("kind") if isinstance(stored, dict) else stored
        for identifier, stored in _stored(units).items()
    }
    return {"units": kinds, "offenders": disposition_offenders(units)}
