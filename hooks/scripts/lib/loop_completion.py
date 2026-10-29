"""Claude completion gates for retrospectives, independent work units, and proofs."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, cast

from .loop_proofs import validate_proofs
from .loop_state_common import LoopState, log

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "skills/agentic-loop/scripts"))
from graph_vocab import disposition_offenders

ABSENT_TEXT = "cost not recorded"
MINER_FAILED_TEXT = "cost unavailable (miner returned no data)"
INCOMPLETE_TEXT = "cost recorded but incomplete (missing "


class CostState(str, Enum):
    """Closed outcome of the retro cost report, fixed where the report is built, never read back from its text."""

    REPORTED = "reported"
    SKIPPED = "skipped_legacy_or_bad_sv"
    MINER_FAILED_OPEN = "miner_failed_open"
    ABSENT = "cost_absent"
    INCOMPLETE = "cost_incomplete"


@dataclass(frozen=True)
class CostReport:
    """The cost outcome and the human message rendered for it."""

    state: CostState
    message: str


def cost_message(retro: dict[str, Any]) -> CostReport:
    """Render the recorded cost and date caveats without recomputing frozen usage."""
    version = retro.get("schema_version")
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version < 2:
        return CostReport(CostState.SKIPPED, "")
    cost = retro.get("cost")
    if not isinstance(cost, dict):
        return CostReport(CostState.ABSENT, ABSENT_TEXT)
    cost = cast(dict[str, Any], cost)
    if not cost:
        return CostReport(CostState.MINER_FAILED_OPEN, MINER_FAILED_TEXT)
    absent = [
        name
        for name in ("total_usd_estimate", "total_tokens")
        if not isinstance(cost.get(name), (int, float, str)) or isinstance(cost.get(name), bool) or cost.get(name) == ""
    ]
    if absent:
        return CostReport(CostState.INCOMPLETE, INCOMPLETE_TEXT + ", ".join(absent) + ")")
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
    return CostReport(CostState.REPORTED, "".join(character if character.isprintable() else " " for character in text))


def validate_work_units(state: dict[str, Any]) -> None:
    """Reject malformed or unfinished independent work units under the v3 contract."""
    units = state.get("work_units")
    if units is None:
        return
    if not isinstance(units, dict):
        raise ValueError("work_units must be an object under schema v3")
    offenders: list[str] = []
    for identifier, unit in cast(dict[str, Any], units).items():
        if not str(identifier).strip():
            offenders.append(repr(identifier))
            continue
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
    if bad := disposition_offenders(cast(dict[str, Any], units)):
        raise ValueError(
            "work_units have an illegal disposition: " + ", ".join(bad) + ".\n"
            "preserve-compat needs a named blocker and a removal ticket; clean-break carries neither."
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
    log(f"hook=loop_stall_guard session={state.session} cost_report={cost.state.value}")
    return [message for message in (withdrawn, cost.message) if message]
