"""Provide synthetic corpus and isolated CLI helpers for workflow audit tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def invoke(name: str, root: Path, *arguments: str, stdin: str = "", own: str = "") -> subprocess.CompletedProcess[str]:
    """Invoke an actual audit CLI without touching user transcript or queue directories."""
    environment = dict(
        os.environ,
        HOME=str(root),
        WORKFLOW_AUDIT_ROOT=str(root),
        CLAUDE_CODE_SESSION_ID=own,
        PYTHONDONTWRITEBYTECODE="1",
    )
    return subprocess.run(
        [sys.executable, str(SCRIPTS / f"{name}.py"), *arguments],
        input=stdin,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )


def transcript(events: list[dict[str, Any]], timestamp: str = "2026-07-06T10:00:00Z") -> str:
    """Wrap tool events in assistant records alongside excluded bookkeeping and prose."""
    records = [
        {"type": "custom-title", "title": "private title"},
        {"type": "user", "message": {"content": "private prose"}, "timestamp": timestamp},
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", **event} for event in events]},
            "timestamp": timestamp,
        },
        {"type": "last-prompt", "prompt": "private resume cache"},
    ]
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"


def place(root: Path, project: str, session: str, contents: str) -> Path:
    """Create one synthetic top-level transcript in a project directory."""
    path = root / project / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def rows(output: str) -> list[dict[str, Any]]:
    """Parse emitted session objects for explicit field assertions."""
    return [json.loads(line) for line in output.splitlines()]
