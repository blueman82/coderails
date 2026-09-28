"""Private filesystem and native-process fixtures for Claude hook tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
HOOKS = ROOT / "hooks/scripts"


class HookTestCase(unittest.TestCase):
    """Provide isolated hook state and literal subprocess invocation helpers."""

    def setUp(self) -> None:
        """Create session-private files and disable only test retry delays."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.environment = {
            **os.environ,
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.directory / "state"),
            "CLAUDE_DISCIPLINE_LOG": str(self.directory / "discipline.log"),
            "CLAUDE_HOOK_MAX_ATTEMPTS": "1",
            "CLAUDE_HOOK_SLEEP_S": "0",
        }
        self.environment.pop("CODERAILS_HEADLESS_RUN", None)
        self.session = "S1"

    def run_hook(self, name: str, payload: dict[str, Any], **environment: str) -> subprocess.CompletedProcess[str]:
        """Run a Python hook with JSON input and capture both output streams."""
        return subprocess.run(
            [sys.executable, str(HOOKS / f"{name}.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**self.environment, **environment},
            check=False,
        )

    def transcript(self, text: str = "", invocations: int = 1) -> Path:
        """Write a native Skill invocation followed by assistant text."""
        path = self.directory / "transcript.jsonl"
        records = [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}]
                },
            }
            for _ in range(invocations)
        ]
        if text:
            records.append({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
        path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
        return path

    def payload(self, transcript: Path) -> dict[str, Any]:
        """Return a session-owned Stop payload outside a Git repository."""
        return {
            "transcript_path": str(transcript),
            "cwd": "/work/project",
            "session_id": self.session,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        }

    def progress(self, status: str = "in-progress", marker: int = 0, **fields: object) -> Path:
        """Write a current-schema minimal state for lifecycle predicates."""
        path = self.directory / "state/-work-project" / self.session / "progress.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "session_id": self.session,
                    "status": status,
                    "loop_id": "loop-test",
                    "revision": 1,
                    "completed_marker": marker,
                    **fields,
                }
            )
        )
        return path

    def git_repo(self, name: str, branch: str = "main") -> Path:
        """Create an isolated Git repository with an explicitly named branch."""
        path = self.directory / name
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(["git", "-C", str(path), "checkout", "-b", branch, "-q"], check=True)
        return path
