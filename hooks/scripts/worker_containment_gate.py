#!/usr/bin/env python3
"""Containment gate: a high-risk implementation unit may not run as an in-process worker while sandboxing is available.

Acts only when ALL hold: tool_name is Agent, subagent_type is coderails:loop-worker, the session is graph-bound,
and containment.resolve() is `sandboxed` (sandbox_workers true or absent, runtime and worker credential present).
Then the unit (from the graph dispatch envelope, node U3[<unit>]) is classified from progress.json
work_units[unit].manifest / write_scope against HIGH_RISK_PREFIXES (an absent manifest cannot prove low risk):
  low risk   allowed, traced containment_fallback_low_risk (the worker should still prefer the sandboxed launcher);
  high risk  denied containment_ack_required unless an owner-signed, single-use `worker_fallback` receipt bound to
             repository + branch + base sha + the unit verifies and is consumed (traced containment_ack_receipt).
Mode fallback/off, non-graph sessions and every other tool or role are untouched. Any own error fails open, traced
containment_gate_failed_open. Separate from loop_dispatch_guard. The owner mints with
`scripts/action_receipt_cli.py approve-action --kind worker_fallback --command 'worker_fallback <unit>'`.
Cooperating-agent safeguard: an agent can edit the config key or the manifest it is judged by.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, read_payload
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.lib.capability_scope import graph_bound
from hooks.scripts.lib.graph_evidence import ENVELOPE_KEY
from hooks.scripts.lib.loop_state_common import read_state
from hooks.scripts.lib.trace_row import append_row
from scripts.lib import action_receipt as ar
from scripts.lib.receipt_signing import resolve_trust_root
from scripts.sandbox import containment

ROLE = "coderails:loop-worker"
COMMAND = "worker_containment"


def unit_of(prompt: object) -> str:
    """The work unit named by the dispatch envelope's node_id U3[<unit>], or empty text."""
    if not isinstance(prompt, str) or not prompt.startswith(ENVELOPE_KEY + "="):
        return ""
    try:
        node = json.loads(prompt.split("\n", 1)[0].split("=", 1)[1]).get("node_id", "")
    except (ValueError, AttributeError):
        return ""
    found = re.fullmatch(r"U3\[(.+)\]", str(node))
    return found[1] if found else ""


def manifest_of(session: str, cwd: str, unit: str) -> list[str]:
    """The unit's declared write scope (manifest + write_scope strings); empty when absent."""
    units = read_state(resolve_path(cwd, session)).get("work_units")
    entry = cast("dict[str, Any]", units).get(unit) if isinstance(units, dict) else None
    entries = cast("dict[str, Any]", entry) if isinstance(entry, dict) else {}
    found: list[object] = []
    for key in ("manifest", "write_scope"):
        value = entries.get(key)
        found += cast("list[object]", value) if isinstance(value, list) else []
    return [item for item in found if isinstance(item, str)]


def acknowledged(session: str, cwd: str, unit: str) -> bool:
    """True when a valid owner-signed worker_fallback receipt for this unit existed and was consumed now."""
    bind = containment.fallback_binding(cwd)
    if bind is None:
        return False
    branch = bind["ref"].removeprefix("refs/heads/")
    proposed = ar.proposed_action(containment.ACK_KIND, containment.ack_command(unit), cwd, branch, bind)
    found, _ = ar.find_valid(
        session, proposed, datetime.now(timezone.utc), None, consume_it=True, signers=resolve_trust_root()[0]
    )
    return found is not None


def main() -> int:
    """Check one Agent payload; fail open on any own error."""
    payload = read_payload()
    request = payload.get("tool_input")
    request = request if isinstance(request, dict) else {}
    if payload.get("tool_name") != "Agent" or request.get("subagent_type") != ROLE:
        return 0
    session = str(payload.get("session_id") or "?")
    cwd = str(payload.get("cwd") or os.getcwd())
    try:
        if not graph_bound(session, cwd) or containment.resolve(cwd)["mode"] != "sandboxed":
            return 0
        unit = unit_of(request.get("prompt"))
        if unit and not containment.is_high_risk(manifest_of(session, cwd, unit)):
            append_row(COMMAND, "allowed", "containment_fallback_low_risk", session)
            return 0
        if unit and acknowledged(session, cwd, unit):
            append_row(COMMAND, "allowed", "containment_ack_receipt", session)
            return 0
        append_row(COMMAND, "denied", "containment_ack_required", session)
        log(f"hook=worker_containment_gate session={session} denied=1 reason_code=containment_ack_required")
        deny(
            "Blocked (containment_ack_required): sandboxed workers are available and this unit's write scope can "
            "touch protected paths (hooks/, scripts/, agents/, schemas ...) or is undeclared. Dispatch it with "
            "`python3 scripts/sandbox/spawn_sandboxed_worker.py <worktree> <prompt_file> <model>`, or the OWNER "
            "acknowledges the in-process fallback once at a terminal: python3 scripts/action_receipt_cli.py "
            f"approve-action --session {session} --kind {containment.ACK_KIND} "
            f"--command '{containment.ack_command(unit or '<unit>')}' --cwd {cwd}"
        )
    except Exception as error:  # noqa: BLE001 - the gate must never break a session; trace and fail open
        append_row(
            COMMAND, "failed_open", "containment_gate_failed_open", session, None, {"error": type(error).__name__}
        )
        print(f"worker_containment_gate failed open: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
