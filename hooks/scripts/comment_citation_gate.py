#!/usr/bin/env python3
"""Deny temporary session-label citations in changed non-Markdown comments."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.hook_common import deny, read_payload

CITATION = re.compile(
    r"\bE\d+:|\bF\d+ (?:fix|:|design)|CHANGE [BC]\d|\bTask A\d+\b|TA-I\d+|"
    r"reviewer finding|eval E\d+|\bWU\d+:|\bC2\b|per the (?:plan|design|session)|per F\d+",
    re.I,
)


def main() -> int:
    """Deny changed code comments that cite ephemeral session evidence."""
    payload = read_payload()
    data = payload.get("tool_input")
    if not isinstance(data, dict):
        return 0
    path = data.get("file_path", "")
    if not isinstance(path, str) or path.endswith(".md"):
        return 0
    values = [data.get(key) for key in ("new_string", "content")]
    edits = data.get("edits", [])
    values += [edit.get("new_string") for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []
    for value in values:
        if isinstance(value, str) and CITATION.search(re.sub(r'"[^"]*"', '""', value.replace(r"\"", "@"))):
            deny(
                "Blocked: comment cites a session-artifact label. State the constraint the code enforces, "
                "not the conversation that produced it."
            )
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
