#!/usr/bin/env python3
"""Deny Bash from an untyped subagent in a graph-bound session.

Denies only when ALL hold: tool_name is Bash, agent_id is present, agent_type is absent/blank, and the
session is graph-bound (session_id known and progress.json carries 'graph').

It is NOT fail-closed in general: it allows when session_id is missing or '?', when progress.json is missing/unreadable
or lacks 'graph', when the harness omits agent_id, and for every tool other than Bash. It also does not force role
dispatch: any present agent_type (even general-purpose) passes; forcing typed dispatch belongs to lane A's
loop_dispatch_guard. reviewer_bash_allowlist keys on agent_type; a call with agent_id but no agent_type would skip it,
which is the one gap this closes. Claude only: Codex PreToolUse payloads carry neither field, so Codex has no
equivalent (see docs/CAPABILITIES.md).
ON by default; `subagent_identity_gate: off` in workflow.config.yaml disables it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, read_payload
from hooks.scripts.lib.capability_scope import graph_bound, has_text
from hooks.scripts.lib.trace_row import append_row
from scripts.lib.config import config_path
from scripts.lib.config_strict import ConfigRejected, strict_settings

REASON = "bash_agent_type_absent"


def main() -> int:
    """Deny Bash with agent_id but no agent_type when the session is graph-bound; the orchestrator is untouched."""
    payload = read_payload()
    typed = has_text(payload.get("agent_type"))
    if payload.get("tool_name") != "Bash" or not has_text(payload.get("agent_id")) or typed:
        return 0
    session = str(payload.get("session_id") or "?")
    cwd = str(payload.get("cwd") or os.getcwd())
    if not graph_bound(session, cwd):
        return 0
    path = config_path(cwd)
    if path:
        try:
            settings = strict_settings(path, session)
        except ConfigRejected as error:
            log(f"hook=subagent_identity_gate session={session} denied=1 reason_code=config_rejected")
            append_row("subagent_identity_gate", "denied", "config_rejected", session)
            deny(f"Blocked (config_rejected): {error}. Fix .coderails/workflow.config.yaml.")
            return 0
        if settings["subagent_identity_gate"] == "off":
            return 0
    log(f"hook=subagent_identity_gate session={session} denied=1 reason_code={REASON}")
    append_row("subagent_identity_gate", "denied", REASON, session)
    deny(
        f"Blocked ({REASON}): this Bash call came from a subagent with no agent_type in a graph-bound session. "
        "Typed roles act through their capability tools; dispatch the role by its subagent_type."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
