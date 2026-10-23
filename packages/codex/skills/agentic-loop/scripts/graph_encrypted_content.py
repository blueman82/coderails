"""Bind an encrypted Codex transcript message to a consumed plaintext hook authorization."""

from __future__ import annotations

import base64
import binascii
from typing import Any, cast

import graph_contract


def check(state: dict[str, Any], node_id: str, attempt: int, wave_id: str, message: object) -> dict[str, Any]:
    """Accept only native encrypted content for an exact hook-authorized dispatch."""
    if graph_contract.dispatch_off() or not isinstance(message, str):
        raise graph_contract.DispatchDeniedError(
            "dispatch_missing_envelope", "native spawn lacks an attested plaintext envelope"
        )
    try:
        raw = base64.b64decode(message, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as error:
        raise graph_contract.DispatchDeniedError(
            "dispatch_missing_envelope", "native spawn is not encrypted content"
        ) from error
    if len(raw) < 73 or raw[0] != 0x80 or (len(raw) - 57) % 16:
        raise graph_contract.DispatchDeniedError("dispatch_missing_envelope", "native spawn is not encrypted content")
    issued = [
        (identifier, record)
        for identifier, record in state["graph"].get("dispatches", {}).items()
        if record.get("node_id") == node_id and record.get("attempt") == attempt and record.get("wave_id") == wave_id
    ]
    if len(issued) != 1 or issued[0][1].get("authorized") != {"tool_use_id": None}:
        raise graph_contract.DispatchDeniedError(
            "dispatch_missing_envelope", "native spawn lacks consumed hook authorization"
        )
    identifier, record = issued[0]
    contract = graph_contract.validate_contract(record.get("contract"))
    if record.get("envelope_version") != graph_contract.ENVELOPE_VERSION or graph_contract.sections_sha256(
        contract
    ) != record.get("prompt_sections_sha256"):
        raise graph_contract.DispatchDeniedError(
            "dispatch_contract_altered", "stored contract no longer matches its sections hash"
        )
    envelope = graph_contract.parse_envelope(graph_contract.prompt_prefix(state, identifier, record))
    graph_contract.check_ownership(state, envelope, live=False)
    return cast(dict[str, Any], record)
