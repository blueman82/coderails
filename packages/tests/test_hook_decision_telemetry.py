"""Hook telemetry keeps typed decision fields for direct and wrapped hooks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import hook_decision, hook_telemetry  # noqa: E402


class HookDecisionTelemetryTests(unittest.TestCase):
    """A telemetry row has a typed decision even without a detailed trace row."""

    def setUp(self) -> None:
        """Use separate temporary graph and telemetry directories."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.telemetry = self.root / "telemetry"
        self.telemetry.mkdir()

    def rows(self) -> list[dict[str, Any]]:
        """Read rows written by the wrapped hook or direct record call."""
        return [json.loads(line) for line in (self.telemetry / "hook_telemetry.jsonl").read_text().splitlines()]

    def test_wrapped_advisory_has_typed_coarse_cause(self) -> None:
        """A hook without a separate trace still records its observed cause."""
        with patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": str(self.telemetry)}):
            self.assertEqual(hook_telemetry.run("agent_model_routing_nudge", lambda: 0), 0)
        (row,) = self.rows()
        record = row["decision_record"]
        self.assertIsInstance(record, dict)
        self.assertEqual(
            (record["hook"], record["decision"], record["reason_code"]), ("agent_model_routing_nudge", "ok", "ok")
        )
        self.assertTrue(record["remediation"])

    def test_catalog_failure_keeps_typed_record(self) -> None:
        """A bad catalog cannot remove the typed fields or change a hook result."""
        with (
            patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": str(self.telemetry)}),
            patch.object(hook_decision, "CATALOG", self.root / "missing.json"),
        ):
            self.assertEqual(hook_telemetry.run("agent_model_routing_nudge", lambda: 0), 0)
        (row,) = self.rows()
        record = row["decision_record"]
        self.assertEqual(record["reason_code"], "ok")
        self.assertEqual(record["remediation"], hook_decision.FALLBACK_REMEDIATION)

    def test_both_native_dispatch_guards_record_denial(self) -> None:
        """The direct graph guards use the shared telemetry wrapper on both providers."""
        cases = (
            ("claude", ROOT / "hooks/scripts/loop_dispatch_guard.py", "Agent", "prompt"),
            ("codex", ROOT / "packages/codex/hooks/scripts/loop_dispatch_guard.py", "spawn_agent", "message"),
        )
        for provider, script, tool, message_field in cases:
            with self.subTest(provider=provider):
                telemetry = self.root / provider
                telemetry.mkdir()
                payload = {
                    "tool_name": tool,
                    "tool_input": {
                        message_field: "CODERAILS_GRAPH_DISPATCH=missing",
                        "subagent_type": "coderails:loop-worker",
                    },
                    "session_id": "test-session",
                    "cwd": str(self.root),
                }
                env = {
                    **os.environ,
                    "CODERAILS_HOOK_TELEMETRY_DIR": str(telemetry),
                    "CLAUDE_AGENTIC_LOOP_DIR": str(self.root / "graphs"),
                    "CODERAILS_AGENTIC_LOOP_DIR": str(self.root / "graphs"),
                }
                process = subprocess.run(
                    [sys.executable, str(script)],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    cwd=self.root,
                    env=env,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertIn("deny", process.stdout)
                (row,) = [json.loads(line) for line in (telemetry / "hook_telemetry.jsonl").read_text().splitlines()]
                self.assertEqual((row["cause"], row["decision_record"]["reason_code"]), ("deny", "deny"))


if __name__ == "__main__":
    unittest.main()
