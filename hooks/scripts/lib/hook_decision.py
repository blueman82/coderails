"""Typed, content-free hook decision fields for local trace rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

CATALOG = Path(__file__).resolve().parents[2] / "messages.json"
FALLBACK_REMEDIATION = "Read the hook reason and retry after you correct its cause."


class DecisionRecord(TypedDict):
    """One hook result with a stable code and a human recovery step."""

    hook: str
    decision: str
    reason_code: str
    params: dict[str, str]
    remediation: str


def _remediation(hook: str, reason_code: str) -> str:
    """Use a known recovery step, including when the optional catalog cannot be read."""
    try:
        raw: object = json.loads(CATALOG.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return FALLBACK_REMEDIATION
        catalog = cast("dict[str, object]", raw)
        reasons_raw = catalog.get("reasons", {})
        if isinstance(reasons_raw, dict):
            reason = cast("dict[str, object]", reasons_raw).get(reason_code)
            if isinstance(reason, dict):
                action = cast("dict[str, object]", reason).get("remediation")
                if isinstance(action, str) and action:
                    return action
        hooks_raw = catalog.get("hooks")
        aliases_raw = catalog.get("aliases", {})
        if not isinstance(hooks_raw, dict) or not isinstance(aliases_raw, dict):
            return FALLBACK_REMEDIATION
        hooks = cast("dict[str, object]", hooks_raw)
        aliases = cast("dict[str, object]", aliases_raw)
        alias = aliases.get(hook, hook)
        message = hooks.get(alias if isinstance(alias, str) else hook)
        if not isinstance(message, dict):
            return FALLBACK_REMEDIATION
        remediation = cast("dict[str, object]", message).get("remediation")
        return remediation if isinstance(remediation, str) and remediation else FALLBACK_REMEDIATION
    except (OSError, UnicodeError, ValueError, TypeError):
        return FALLBACK_REMEDIATION


def make_record(hook: object, decision: object, reason_code: object, params: object = None) -> DecisionRecord:
    """Use the emitted reason and the catalog remediation; refuse malformed fields."""
    if any(not isinstance(value, str) or not value.strip() for value in (hook, decision, reason_code)):
        raise ValueError("hook decision needs nonempty text fields")
    if params is not None:
        if not isinstance(params, dict):
            raise ValueError("hook decision params must map names to text")
        raw_params = cast("dict[object, object]", params)
        if any(not isinstance(key, str) or not key or not isinstance(value, str) for key, value in raw_params.items()):
            raise ValueError("hook decision params must map names to text")
    hook_text, decision_text, reason_text = cast("tuple[str, str, str]", (hook, decision, reason_code))
    typed_params = cast("dict[str, str] | None", params)
    return {
        "hook": hook_text,
        "decision": decision_text,
        "reason_code": reason_text,
        "params": dict(typed_params or {}),
        "remediation": _remediation(hook_text, reason_text),
    }
