#!/usr/bin/env python3
"""Restrict reviewer and scout subagents to exact read-only Bash argv prefixes."""

from __future__ import annotations

import hashlib
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
# Flags that make an otherwise read-only command write or execute. Denylist for git/grep/etc.; rg is allowlisted below
# because its flag surface is open-ended (e.g. --hostname-bin executes a program).
DANGEROUS_FLAG = re.compile(r"^--(output|pre|pre-glob|ext-diff|textconv|hostname-bin)(=|$)")
PLAIN = frozenset({"ls", "cat", "head", "tail", "wc", "grep", "rg", "sha256sum"})
GIT = frozenset({"status", "log", "diff", "show", "blame"})
RG_LONG = frozenset(
    [
        "line-number",
        "ignore-case",
        "smart-case",
        "case-sensitive",
        "word-regexp",
        "fixed-strings",
        "files-with-matches",
        "files-without-match",
        "count",
        "only-matching",
        "invert-match",
        "hidden",
        "no-heading",
        "heading",
        "with-filename",
        "no-filename",
        "files",
        "multiline",
        "glob",
        "iglob",
        "type",
        "type-not",
        "max-count",
        "max-depth",
        "context",
        "after-context",
        "before-context",
        "regexp",
        "no-messages",
        "no-ignore",
        "column",
        "null",
        "color",
        "line-regexp",
    ]
)
RG_SHORT = re.compile(r"^-[A-Za-y0-9]+$")  # short clusters; -z (decompressor exec) is excluded


def rg_ok(args: list[str]) -> bool:
    """Per-flag allowlist for rg: unknown long flags and -z are refused; everything after `--` is a pattern/path."""
    for token in args:
        if token == "--":
            return True
        if token.startswith("--"):
            if token[2:].split("=", 1)[0] not in RG_LONG:
                return False
        elif token.startswith("-") and token != "-" and not RG_SHORT.match(token):
            return False
    return True


def verdict(command: str) -> str | None:
    """Return None for a single read-only allowlisted command, else the deny reason code naming the cause."""
    if META.search(command):
        return f"{REASON}_meta"
    try:
        argv = shlex.split(command)
    except ValueError:
        return f"{REASON}_parse"
    if not argv:
        return f"{REASON}_argv"
    if any(DANGEROUS_FLAG.match(token) for token in argv) or (argv[0] == "rg" and not rg_ok(argv[1:])):
        return f"{REASON}_flag"
    if argv[0] in PLAIN:
        return None
    if argv[0] == "git" and len(argv) > 1 and argv[1] in GIT:
        return None
    if argv[0] == "gh" and argv[1:3] in (["pr", "view"], ["pr", "list"]) and "--json" in argv:
        return None
    return f"{REASON}_argv"


def allowed(command: str) -> bool:
    """Return True only for a single read-only command whose argv prefix is on the allowlist."""
    return verdict(command) is None


def agent_name(value: object) -> str:
    """Strip a plugin namespace (`coderails:design-scout` -> `design-scout`) from a payload agent_type."""
    return value.rsplit(":", 1)[-1] if isinstance(value, str) else ""


def main() -> int:
    """Deny non-allowlisted Bash from guarded agent types; every other caller is untouched."""
    payload = read_payload()
    if payload.get("tool_name") != "Bash" or agent_name(payload.get("agent_type")) not in GUARDED:
        return 0
    data = payload.get("tool_input")
    command = data.get("command") if isinstance(data, dict) else None
    if not isinstance(command, str) or not command:
        return 0
    code = verdict(command)
    if code is None:
        return 0
    session = str(payload.get("session_id") or "?")
    agent = agent_name(payload["agent_type"])
    argv0 = (command.split() or ["?"])[0][:40]
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()[:12]
    log(
        f"hook=reviewer_bash_allowlist agent_type={agent} session={session} denied=1 "
        f"reason_code={code} argv0={argv0} sha={digest}"
    )
    append_row("reviewer_bash_allowlist", "denied", code, session, inputs={"command": command})
    deny(
        f"Blocked ({code}): reviewer/scout agents may run only single read-only commands "
        "(ls, cat, head, tail, wc, grep, rg, sha256sum, git status|log|diff|show|blame, gh pr view|list --json). "
        "No chaining, redirection, substitution or interpreters."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
