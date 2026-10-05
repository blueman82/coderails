#!/usr/bin/env python3
"""Fail closed on Bash from a subagent that carries no usable agent_type inside a graph-bound session.

reviewer_bash_allowlist keys on agent_type; a call with agent_id but no agent_type would skip it. Claude only: Codex
PreToolUse payloads carry neither field, so Codex has no equivalent (see docs/CAPABILITIES.md).
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
from scripts.lib.config import config_path, config_value

REASON = "bash_agent_type_absent"


def main() -> int:
    """Deny Bash with agent_id but no agent_type when the session is graph-bound; the orchestrator is untouched."""
    payload = read_payload()
    typed = has_text(payload.get("agent_type"))
    if payload.get("tool_name") != "Bash" or not has_text(payload.get("agent_id")) or typed:
        return 0
    session = str(payload.get("session_id") or "?")
    cwd = str(payload.get("cwd") or os.getcwd())
    path = config_path(cwd)
    if (config_value(path, "subagent_identity_gate") if path else "") == "off" or not graph_bound(session, cwd):
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
