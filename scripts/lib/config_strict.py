"""Strict reading of the workflow config: reject instead of report, resolve safety controls, pick the worker mode.

`load_config` (config.py) never raises and only reports. A gate that guards an action calls `strict_settings`, which
raises ConfigRejected on any unknown key, bad type, enum violation or unreadable file, so a typo cannot silently
turn a control off. An absent config file is not read at all (repos not using coderails stay inert); that is a limit.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

from .config import SCHEMA_PATH, load_config, report_findings

# The same executables scripts/sandbox/spawn_sandboxed_worker.py requires before it launches under srt.
SRT_EXECUTABLES = ("npx", "gh")


def describe(finding: dict[str, str]) -> str:
    """One finding as text, with the did-you-mean hint when there is one."""
    text = f"{finding['code']}:{finding['key']}" if finding["key"] else finding["code"]
    return f"{text} (did you mean '{finding['hint']}'?)" if finding["hint"] else text


class ConfigRejected(Exception):  # noqa: N818 - the name is the contract gates import
    """The config file has findings; carries them so a gate can name the key and its closest match."""

    def __init__(self, findings: list[dict[str, str]]) -> None:
        """Keep the findings beside the message."""
        super().__init__("config_rejected: " + "; ".join(describe(f) for f in findings))
        self.findings = findings


def strict_settings(path: str | Path, session: str = "") -> dict[str, Any]:
    """Typed values for path, or ConfigRejected(findings). The findings are also traced like settings() does."""
    values, findings = load_config(path)
    if findings:
        report_findings(findings, session)
        raise ConfigRejected(findings)
    return values


def _properties() -> dict[str, Any]:
    """The schema's top-level properties; empty when the schema cannot be read."""
    try:
        data = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast("dict[str, Any]", cast("dict[str, Any]", data).get("properties", {})) if isinstance(data, dict) else {}


def controls_resolved(values: dict[str, Any]) -> dict[str, Any]:
    """Effective value of every schema property flagged control:true (dotted key), a missing section using defaults."""
    resolved: dict[str, Any] = {}

    def walk(properties: dict[str, Any], scope: object, prefix: str) -> None:
        for key, spec in properties.items():
            held = cast("dict[str, Any]", scope) if isinstance(scope, dict) else {}
            value = held[key] if held.get(key) is not None else spec.get("default")
            if spec.get("control"):
                resolved[prefix + key] = value
            walk(spec.get("properties", {}), value, prefix + key + ".")

    walk(_properties(), values, "")
    return resolved


def sandbox_mode(values: dict[str, Any]) -> str:
    """Return sandboxed, in-process or in-process-fallback:<reason> for the sandbox_workers value in values."""
    if controls_resolved(values).get("sandbox_workers") is not True:
        return "in-process"
    missing = next((name for name in SRT_EXECUTABLES if not shutil.which(name)), "")
    return f"in-process-fallback:{missing}_missing" if missing else "sandboxed"
