#!/usr/bin/env python3
"""Lock the opt-in configured-command and failure-output limits at the native hook boundary."""

from __future__ import annotations

import gzip
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HOOKS, HookTestCase


class TestGateContractTests(HookTestCase):
    """Configured shell commands remain user-authored commands with bounded displayed output."""

    def execute(self, configured: str) -> dict[str, Any]:
        """Run one commit check in a private project with its exact configured first line."""
        self.environment["CODERAILS_TEST_OUTPUT_DIR"] = str(self.directory / "logs")
        path = self.directory / ".claude/test_command"
        path.parent.mkdir(exist_ok=True)
        path.write_text(configured)
        result = subprocess.run(
            [sys.executable, str(HOOKS / "test_gate.py")],
            input=json.dumps({"tool_input": {"command": "git commit -m verify"}}),
            text=True,
            capture_output=True,
            cwd=self.directory,
            env=self.environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout else {}

    def test_failure_retains_full_log_and_reports_location(self) -> None:
        """Neither the first error nor Unicode at the former cutoff may disappear."""
        writer = self.directory / "configured_test.py"
        text = "FIRST ERROR\n" + "x" * 1499 + "€\n" + "last\n" * 50
        writer.write_text(f"import sys\nsys.stdout.write({text!r})\nraise SystemExit(1)\n")
        result = self.execute(f'"{sys.executable}" "{writer}"\n')
        self.assertEqual(result["permissionDecision"], "deny")
        reason = result["permissionDecisionReason"]
        self.assertIn("Full log:", reason)
        logs = list((self.directory / "logs").rglob("output.log.gz"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(gzip.decompress(logs[0].read_bytes()).decode(), text)
        self.assertIn(str(logs[0]), reason)
        self.assertNotIn("FIRST ERROR", reason)
        record = json.loads(logs[0].with_name("run.json").read_text())
        self.assertEqual(record["total_bytes"], len(text.encode()))
        self.assertEqual(record["total_lines"], 52)
        self.assertEqual(record["exit_code"], 1)

    def test_only_first_configured_line_executes_with_shell_semantics(self) -> None:
        """A compound configured line runs literally; subsequent file lines are not commands."""
        self.assertEqual(self.execute("printf 'configured' > marker && true\nfalse\n"), {})
        self.assertEqual((self.directory / "marker").read_text(), "configured")
        result = self.execute("printf 'actual failure'; false\ntrue\n")
        self.assertEqual(result["permissionDecision"], "deny")
        self.assertTrue(
            any(
                gzip.decompress(p.read_bytes()).decode() == "actual failure"
                for p in (self.directory / "logs").rglob("output.log.gz")
            )
        )
        self.assertEqual(self.execute("\nfalse\n"), {})


if __name__ == "__main__":
    unittest.main()
