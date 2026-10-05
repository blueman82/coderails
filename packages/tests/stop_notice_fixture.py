"""Shared driver for the Stop-block notice tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.tests.lib.claude_transcript_fixture import append  # noqa: E402
from packages.tests.provider_fixture import Provider  # noqa: E402


class StopNoticeBase(unittest.TestCase):
    """Isolated claude and codex providers plus a real-hook Stop driver."""

    def setUp(self) -> None:
        """Isolated claude and codex providers."""
        patch = mock.patch.dict("os.environ", {}, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def payload(self, provider: Provider, message: str = "done") -> dict[str, Any]:
        """Append the Claude transcript and build one Stop payload."""
        if provider.name == "claude":
            skill = {"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}
            append(provider.parent, {"type": "assistant", "message": {"content": [skill]}})
            append(provider.parent, {"type": "assistant", "message": {"content": [{"type": "text", "text": message}]}})
        return {
            "session_id": provider.session,
            "cwd": str(provider.home),
            "hook_event_name": "Stop",
            "transcript_path": str(provider.parent),
            "last_assistant_message": message,
        }

    def stop(self, provider: Provider, message: str = "done") -> str:
        """Run one Stop and return the systemMessage ('' when deduplicated); the raw result stays in self.last."""
        hook = "loop_stall_guard" if provider.name == "claude" else "graph_completion_guard"
        self.last = provider.hook(hook, self.payload(provider, message))
        output: dict[str, Any] = json.loads(self.last.stdout) if self.last.stdout else {}
        return str(output.get("systemMessage", ""))

    def age(self, provider: Provider, seconds: float) -> None:
        """Make every dedupe marker look `seconds` older."""
        for marker in provider.path.parent.glob(".human-approval-*"):
            old = marker.stat().st_mtime - seconds
            os.utime(marker, (old, old))

    def recover_rows(self, provider: Provider) -> int:
        """Count recover-wave trace rows written beside the state."""
        trace = provider.path.with_name("recovery-trace.jsonl")
        return len(trace.read_text().splitlines()) if trace.is_file() else 0
