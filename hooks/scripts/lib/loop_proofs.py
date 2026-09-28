"""Validate frozen proof commands against the owning Claude transcript."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .discipline_common import content, records, tool_uses


def proof_executions(transcript: str) -> tuple[dict[str, str], dict[str, bool]]:
    """Index final foreground Bash invocations and their native result flags."""
    executions: dict[str, str] = {}
    results: dict[str, bool] = {}
    for record in records(transcript):
        for tool in tool_uses(record):
            data = tool.get("input")
            identifier = tool.get("id")
            if (
                tool.get("name") != "Bash"
                or not isinstance(data, dict)
                or (
                    cast(dict[str, Any], data).get("run_in_background") is not None
                    and cast(dict[str, Any], data).get("run_in_background") is not False
                )
            ):
                continue
            command = cast(dict[str, Any], data).get("command")
            if isinstance(identifier, str) and identifier and isinstance(command, str) and command.strip():
                executions[command.strip()] = identifier
        value = content(record)
        if record.get("type") != "user" or not isinstance(value, list):
            continue
        for block in cast(list[object], value):
            if not isinstance(block, dict) or cast(dict[str, Any], block).get("type") != "tool_result":
                continue
            identifier = cast(dict[str, Any], block).get("tool_use_id")
            if isinstance(identifier, str) and identifier:
                results[identifier] = cast(dict[str, Any], block).get("is_error") is True
    return executions, results


def _proof_verdict(
    item: object,
    identifier: str,
    executions: dict[str, str],
    results: dict[str, bool],
    withdrawn: bool,
    proof_ids: set[str],
) -> tuple[str, str]:
    if not isinstance(item, dict):
        return "unverifiable", ""
    value = cast(dict[str, Any], item)
    command, reason = value.get("cmd"), value.get("withdrawn_reason")
    if withdrawn and identifier in proof_ids:
        return "duplicate_id", ""
    if not isinstance(command, str) or not command.strip():
        return "badcmd", ""
    if withdrawn and (not isinstance(reason, str) or not reason.strip()):
        return "badreason", ""
    execution = executions.get(command.strip())
    if execution is None:
        return "unexecuted", ""
    if withdrawn:
        if results.get(execution) is not True:
            return "not_failed", ""
        return "ok", str(reason).strip().split("\n")[0]
    if execution not in results:
        return "unexecuted", ""
    return ("failed" if results[execution] else "satisfied"), ""


def validate_proofs(path: Path, state: dict[str, Any], transcript: str) -> str:
    """Return withdrawn-proof disclosure, raising when any frozen proof lacks evidence."""
    try:
        document: object = json.loads(path.read_text())
    except FileNotFoundError as error:
        disposition = state.get("proof_disposition")
        if isinstance(disposition, str) and (disposition == "none" or disposition.startswith("none:")):
            return ""
        raise ValueError(
            "no proof.json and no proof_disposition explaining why; freeze proof.json or record none: <reason>"
        ) from error
    except (OSError, ValueError) as error:
        raise ValueError("proof.json is malformed (not valid JSON)") from error
    if not isinstance(document, dict):
        raise ValueError("proof.json is malformed (not an object)")
    value = cast(dict[str, Any], document)
    version = value.get("schema_version")
    if not isinstance(version, (int, float)) or isinstance(version, bool) or version < 1:
        raise ValueError("proof.json has no valid schema_version (>= 1 required)")
    proofs: object = value.get("proofs") if value.get("proofs") is not None else []
    withdrawn: object = value.get("withdrawn_proofs") if value.get("withdrawn_proofs") is not None else []
    if not isinstance(proofs, list) or not isinstance(withdrawn, list):
        raise ValueError("proof.json .proofs and .withdrawn_proofs must be arrays")
    proofs = cast(list[object], proofs)
    withdrawn = cast(list[object], withdrawn)
    if len(proofs) + len(withdrawn) > 100:
        raise ValueError(f"proof.json has {len(proofs) + len(withdrawn)} proofs+withdrawn_proofs; cap is 100")
    executions, results = proof_executions(transcript)
    proof_ids = {
        cast(dict[str, Any], item)["id"]
        for item in proofs
        if isinstance(item, dict)
        and isinstance(cast(dict[str, Any], item).get("id"), str)
        and cast(dict[str, Any], item)["id"]
    }
    offenders: list[str] = []
    disclosures: list[str] = []
    for is_withdrawn, collection, prefix in ((False, proofs, "P"), (True, withdrawn, "W")):
        for index, item in enumerate(collection):
            identifier = cast(dict[str, Any], item).get("id") if isinstance(item, dict) else None
            identifier = identifier if isinstance(identifier, str) and identifier else f"{prefix}{index}"
            verdict, reason = _proof_verdict(
                collection[index], identifier, executions, results, is_withdrawn, proof_ids
            )
            if verdict not in {"satisfied", "ok"}:
                offenders.append(f"{identifier}({verdict})")
            elif is_withdrawn:
                disclosures.append(f"{identifier}: {reason}")
    if offenders:
        raise ValueError(
            "these frozen proofs are not verified: " + ", ".join(offenders) + ".\n"
            "Run each named proof's cmd VERBATIM as its own single Bash command in THIS session, "
            "in the foreground. Withdrawn proofs require an observed failure and withdrawn_reason."
        )
    return "Withdrawn proofs: " + "; ".join(disclosures) if disclosures else ""
