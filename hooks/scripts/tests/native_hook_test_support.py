"""Isolated stdlib fixtures for native Claude hook subprocess contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HOOKS = Path(__file__).resolve().parent.parent


class HookCase(unittest.TestCase):
    """Give each hook case private logs, HOME, transcripts, and graph flag storage."""

    def setUp(self) -> None:
        """Isolate every filesystem effect from the real user configuration."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.loop = self.directory / "loops"
        self.log = self.directory / "discipline.log"
        self.environment = os.environ | {
            "HOME": str(self.directory / "home"),
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            "CLAUDE_DISCIPLINE_LOG": str(self.log),
            "CLAUDE_HOOK_SLEEP_S": "0",
            "CLAUDE_HOOK_MAX_ATTEMPTS": "2",
            "AGENT_ONLY_GATE_ENFORCE": "0",
            "CODERAILS_HEADLESS_RUN": "0",
        }

    def invoke(self, name: str, payload: object, **environment: str) -> subprocess.CompletedProcess[str]:
        """Run one hook with a JSON object or deliberately malformed raw payload."""
        return subprocess.run(
            [sys.executable, str(HOOKS / f"{name}.py")],
            input=payload if isinstance(payload, str) else json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.environment | environment,
            check=False,
        )

    def output(self, name: str, payload: object, **environment: str) -> dict[str, Any]:
        """Require a successful hook process and parse its optional JSON output."""
        result = self.invoke(name, payload, **environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def denied(self, name: str, payload: object, **environment: str) -> bool:
        """Read the native PreToolUse decision without treating diagnostics as denial."""
        decision = self.output(name, payload, **environment).get("hookSpecificOutput", {}).get("permissionDecision")
        return bool(decision == "deny")

    def transcript(self, text: str) -> Path:
        """Write a single native assistant text message as compact JSONL."""
        path = self.directory / "transcript.jsonl"
        path.write_text(
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n",
            encoding="utf-8",
        )
        return path

    def repository(self, name: str, branch: str) -> Path:
        """Create an uncommitted fixture repository on a named branch."""
        path = self.directory / name
        path.mkdir()
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        self.branch(path, branch)
        return path

    def branch(self, path: Path, branch: str) -> None:
        """Select a fixture branch without creating commits or changing source."""
        subprocess.run(["git", "-C", str(path), "symbolic-ref", "HEAD", f"refs/heads/{branch}"], check=True)

    def flag(self, session: str) -> Path:
        """Stamp only the session's crack-on flag."""
        directory = self.loop / session
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "crack_on_active").touch()
        return directory
