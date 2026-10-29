"""Reject a completed native spawn whose plaintext graph envelope is absent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import graph_semantics
from graph_identity import GraphError, new_evidence_writes_enabled
from graph_invalid_evidence import bind_invalid_dispatch
from graph_io import load, locked, write
from graph_recovery import trace, traced_refusal


def reject_invalid_dispatch(path: Path, session: str, node: str, wave_id: str, apply: bool = True) -> dict[str, Any]:
    """Count an invalid spawn as a failed attempt and preserve its native reference."""
    with locked(path):
        state = load(path)
        if state["session_id"] != session:
            raise GraphError("session does not own this loop")
        active = state["graph"]["active_wave"]
        if active is None or active["wave_id"] != wave_id or active["nodes"] != [node]:
            raise GraphError("wave and node must match the single active dispatch")
        with traced_refusal(path, state, "reject-invalid-dispatch", session):
            if apply and not new_evidence_writes_enabled():
                raise GraphError("set CODERAILS_A6_EVIDENCE_WRITE=on after reader verification")
            reference = bind_invalid_dispatch(state, node)
            transition = graph_semantics.record_wave(
                state, wave_id, {node: {"outcome": "failed", "evidence": "native dispatch missing plaintext envelope"}}
            )
            proposed = cast(dict[str, Any], transition["state"])
            proposed["graph"]["nodes"][node]["evidence"].append(reference)
            graph_semantics.validate(proposed)
            if apply:
                write(path, proposed)
        trace(
            path,
            proposed if apply else state,
            "recorded" if apply else "reported",
            "dispatch_missing_envelope",
            {"session": session},
            [(node, reference["attempt"], None)],
            "reject-invalid-dispatch",
        )
        return {
            "wave_id": wave_id,
            "node": node,
            "revision": proposed["revision"],
            "status": proposed["graph"]["nodes"][node]["status"],
            "reason_code": "dispatch_missing_envelope",
            "applied": apply,
        }
