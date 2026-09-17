#!/usr/bin/env python3
"""Reject session-only citations added to non-Markdown code comments."""

from __future__ import annotations

import re
from typing import cast

from hook_common import deny, payload_object, read_input

FILE_HEADER = re.compile(r"^\*\*\* (Add|Update) File: (.*)$")
CITATION = re.compile(
    r"\bE\d+:|\bF\d+ (fix|:|design)|CHANGE [BC]\d|\bTask A\d+\b|TA-I\d+|reviewer finding|"
    r"eval E\d+|\bWU\d+:|\bC2\b|per the (plan|design|session)|per F\d+",
    re.IGNORECASE,
)
DENIAL = (
    "A new code comment cites a temporary session label. State the lasting constraint instead of referring "
    "to the plan, session, eval, task, or reviewer finding."
)


def added_code_lines(command: str) -> list[str]:
    """Return added non-Markdown lines from an apply-patch command."""
    markdown = False
    lines: list[str] = []
    for line in command.splitlines():
        if match := FILE_HEADER.match(line):
            markdown = match.group(2).endswith(".md")
        elif line.startswith("*** Delete File:"):
            markdown = True
        elif not markdown and line.startswith("+"):
            lines.append(line[1:])
    return lines


def uncited(line: str) -> str:
    """Mask quoted strings as the established shell gate does before matching."""
    return re.sub(r'"[^"]*"', '""', line.replace(r"\"", "@"))


def main() -> int:
    """Deny an apply-patch payload that adds a temporary citation to code."""
    payload = payload_object(read_input())
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    command = cast(dict[str, object], tool_input).get("command")
    if not isinstance(command, str) or not any(CITATION.search(uncited(line)) for line in added_code_lines(command)):
        return 0
    deny(DENIAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
