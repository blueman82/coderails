"""Claude completion gates for retrospectives, independent work units, and proofs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, cast

from .loop_proofs import validate_proofs
from .loop_state_common import LoopState, log


def cost_message(retro: dict[str, Any]) -> str:
    """Render the recorded cost and date caveats without recomputing frozen usage."""
    version = retro.get("schema_version")
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version < 2:
        return ""
    cost = retro.get("cost")
    if not isinstance(cost, dict):
        return "cost not recorded"
    cost = cast(dict[str, Any], cost)
    if not cost:
        return "cost unavailable (miner returned no data)"
    absent = [
        name
        for name in ("total_usd_estimate", "total_tokens")
        if not isinstance(cost.get(name), (int, float, str)) or isinstance(cost.get(name), bool) or cost.get(name) == ""
    ]
    if absent:
        return "cost recorded but incomplete (missing " + ", ".join(absent) + ")"
    usd, tokens = cost["total_usd_estimate"], cost["total_tokens"]
    date = cost.get("prices_as_of", "")
    age = date if isinstance(date, str) else ""
    try:
        stamp = datetime.strptime(age, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = int((datetime.now(timezone.utc) - stamp).total_seconds() / 86400)
        age = f"prices as of {date}, {days} days old"
        if days < 0:
            age = f"prices as of {date}, dated in the future (check the date)"
        elif days > 14:
            age += " (checks the date only, not the rates) — verify at claude.com/pricing and bump prices_as_of"
    except ValueError:
        pass
    try:
        usd_display = f"{float(usd):.2f}"
    except (ValueError, TypeError):
        usd_display = str(usd)
    text = f"Loop cost: ${usd_display} ({tokens} tokens), {age}"
    return "".join(character if character.isprintable() else " " for character in text)


def validate_work_units(state: dict[str, Any]) -> None:
    """Reject malformed or unfinished independent work units under the v3 contract."""
    units = state.get("work_units")
    if units is None:
        return
    if not isinstance(units, dict):
        raise ValueError("work_units must be an object under schema v3")
    offenders: list[str] = []
    for identifier, unit in cast(dict[str, Any], units).items():
        if isinstance(unit, dict) and cast(dict[str, Any], unit).get("status") == "done":
            continue
        if isinstance(unit, dict) and cast(dict[str, Any], unit).get("status") == "dropped":
            reason = cast(dict[str, Any], unit).get("dropped_reason")
            if isinstance(reason, str) and reason.strip():
                continue
        offenders.append(str(identifier))
    if offenders:
        raise ValueError(
            "work_units are unfinished: " + ", ".join(offenders) + ".\n"
            'Every work_unit must be "done", or "dropped" with a non-empty dropped_reason.'
        )


def validate_completion(state: LoopState, transcript: str) -> list[str]:
    """Validate provider-owned completion artifacts and return human disclosures."""
    path = state.path.parent / "retro.json"
    try:
        raw: object = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        reason = "absent" if isinstance(error, FileNotFoundError) else "malformed"
        log(f"hook=loop_stall_guard session={state.session} retro={reason} blocked=1")
        raise ValueError(
            f"retro.json is {reason}. Phase 13 teardown writes retro.json before declaring complete."
        ) from error
    if not isinstance(raw, dict):
        raise ValueError("retro.json is malformed")
    retro = cast(dict[str, Any], raw)
    version = retro.get("schema_version")
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version < 1:
        raise ValueError("retro.json is wrong_schema; schema_version >= 1 required")
    validate_work_units(state.data)
    withdrawn = validate_proofs(state.path.parent / "proof.json", state.data, transcript)
    cost = cost_message(retro)
    outcome = "reported"
    if not cost:
        outcome = "skipped_legacy_or_bad_sv"
    elif cost.startswith("cost unavailable"):
        outcome = "miner_failed_open"
    elif cost.startswith("cost not recorded"):
        outcome = "cost_absent"
    elif cost.startswith("cost recorded but incomplete"):
        outcome = "cost_incomplete"
    log(f"hook=loop_stall_guard session={state.session} cost_report={outcome}")
    return [message for message in (withdrawn, cost) if message]
