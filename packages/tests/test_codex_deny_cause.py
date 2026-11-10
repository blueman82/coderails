"""Codex hook denials produce valid output and record telemetry cause deny."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "codex/hooks/scripts"


class DenyCauseTests(unittest.TestCase):
    """Codex hooks record deny for blocked commands and ok for commands they allow."""

    def run_hook(self, name: str, payload: Mapping[str, object], data: str) -> tuple[int, str, list[str]]:
        """Run a hook as a real process and return exit code, stdout and recorded causes."""
        env = {
            **os.environ,
            "CODERAILS_HOOK_TELEMETRY_DIR": data,
            "CODERAILS_TEST_OUTPUT_DIR": str(Path(data) / "test-output"),
            "PLUGIN_DATA": data,
        }
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / f"{name}.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=SCRIPTS,
            env=env,
            timeout=60,
        )
        log = Path(data) / "hook_telemetry.jsonl"
        causes = [json.loads(line)["cause"] for line in log.read_text().splitlines()] if log.exists() else []
        return proc.returncode, proc.stdout, causes

    def test_destructive_bash_gate(self) -> None:
        """Test the owner-config and pattern denies record deny; a benign command records ok."""
        with tempfile.TemporaryDirectory() as tmp:

            def run(command: str) -> tuple[int, str, list[str]]:
                return self.run_hook("destructive_bash_gate", {"tool_input": {"command": command}, "cwd": tmp}, tmp)

            for command, reason_prefix in (
                ("cat .codex/config.toml", "Destructive pattern detected: native Codex owner configuration path"),
                ("git reset " + "--hard", "Destructive pattern detected:"),
            ):
                with self.subTest(command=command):
                    code, out, causes = run(command)
                    self.assertEqual((code, causes[-1]), (0, "deny"))
                    envelope = json.loads(out)
                    self.assertEqual(set(envelope), {"hookSpecificOutput"})
                    decision = envelope["hookSpecificOutput"]
                    self.assertEqual(
                        set(decision),
                        {
                            "hookEventName",
                            "permissionDecision",
                            "permissionDecisionReason",
                        },
                    )
                    self.assertEqual(decision["hookEventName"], "PreToolUse")
                    self.assertEqual(decision["permissionDecision"], "deny")
                    self.assertTrue(decision["permissionDecisionReason"].startswith(reason_prefix))
                    self.assertIn(command, decision["permissionDecisionReason"])
            code, out, causes = run("git status")
            self.assertEqual((code, out, causes), (0, "", ["deny", "deny", "ok"]))

    def test_verification_volume_ceiling(self) -> None:
        """Test the third full-suite run records deny; the first records ok."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"tool_input": {"command": "python3 hooks/scripts/tests/run_all.py"}, "cwd": tmp}
            code, out, causes = self.run_hook("verification_volume_ceiling", payload, tmp)
            self.assertEqual((code, out, causes), (0, "", ["ok"]))
            self.run_hook("verification_volume_ceiling", payload, tmp)
            code, out, causes = self.run_hook("verification_volume_ceiling", payload, tmp)
            decision = json.loads(out)["hookSpecificOutput"]
            self.assertEqual((code, decision["permissionDecision"], causes[2:]), (0, "deny", ["deny"]))
            self.assertIn("This is run 3 of the same full-suite", decision["permissionDecisionReason"])
            self.assertIn("The third and later full re-runs are blocked", decision["permissionDecisionReason"])

    def test_test_gate(self) -> None:
        """Test a failing trusted test command records deny; a passing one records ok."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            config = repo / ".git/coderails/test_command"
            config.parent.mkdir()
            payload = {"tool_input": {"command": "git commit -m x"}, "cwd": str(repo)}
            data = str(Path(tmp) / "data")
            config.write_text("true\n")
            code, out, causes = self.run_hook("test_gate", payload, data)
            self.assertEqual((code, out, causes), (0, "", ["ok"]))
            config.write_text("false\n")
            code, out, causes = self.run_hook("test_gate", payload, data)
            self.assertEqual((code, causes[1:]), (0, ["deny"]))
            decision = json.loads(out)["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertTrue(decision["permissionDecisionReason"].startswith("Test gate failed for: false"))


if __name__ == "__main__":
    unittest.main()
