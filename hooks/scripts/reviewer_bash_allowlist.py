#!/usr/bin/env python3
"""Restrict reviewer and scout subagents to exact read-only Bash argv prefixes."""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, log, read_payload
from hooks.scripts.lib.trace_row import append_row

GUARDED = frozenset(
    {"deploy-safety-reviewer", "design-scout", "disposition-scout", "preflight-scout", "source-auditor"}
)
REASON = "bash_allowlist_deny"
# Rejected on sight, before any parsing: chaining, substitution, redirection, newlines.
META = re.compile(r"[;|&`<>\n\r]|\$\(")
# Flags that make an otherwise read-only command write or execute.
DANGEROUS_FLAG = re.compile(r"^--(output|pre|pre-glob|ext-diff|textconv)(=|$)")
PLAIN = frozenset({"ls", "cat", "head", "tail", "wc", "grep", "rg", "sha256sum"})
GIT = frozenset({"status", "log", "diff", "show", "blame"})


def allowed(command: str) -> bool:
    """Return True only for a single read-only command whose argv prefix is on the allowlist."""
    if META.search(command):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    if not argv or any(DANGEROUS_FLAG.match(token) for token in argv):
        return False
    if argv[0] in PLAIN:
        return True
    if argv[0] == "git":
        return len(argv) > 1 and argv[1] in GIT
    if argv[0] == "gh":
        return argv[1:3] in (["pr", "view"], ["pr", "list"]) and "--json" in argv
    return False


def main() -> int:
    """Deny non-allowlisted Bash from guarded agent types; every other caller is untouched."""
    payload = read_payload()
    if payload.get("tool_name") != "Bash" or payload.get("agent_type") not in GUARDED:
        return 0
    data = payload.get("tool_input")
    command = data.get("command") if isinstance(data, dict) else None
    if not isinstance(command, str) or not command or allowed(command):
        return 0
    session = str(payload.get("session_id") or "?")
    agent = payload["agent_type"]
    log(f"hook=reviewer_bash_allowlist agent_type={agent} session={session} denied=1 reason_code={REASON}")
    append_row("reviewer_bash_allowlist", "denied", REASON, session, inputs={"command": command})
    deny(
        "Blocked: reviewer/scout agents may run only single read-only commands "
        "(ls, cat, head, tail, wc, grep, rg, sha256sum, git status|log|diff|show|blame, gh pr view|list --json). "
        "No chaining, redirection, substitution or interpreters."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
