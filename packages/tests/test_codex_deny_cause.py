"""Codex hooks that print their own deny JSON record telemetry cause deny; allows stay ok; output is unchanged."""

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
ENVELOPE = '{{"hookSpecificOutput": {{"hookEventName": "PreToolUse", "permissionDecision": "deny", {rest}}}}}\n'
OWNER = (
    '"patternId": "codex-owner-config", "permissionDecisionReason": "Destructive pattern detected: native Codex '
    "owner configuration path\\nFull command: cat .codex/config.toml\\nThis command is permanently blocked. "
    'Safe route: these owner-only files must be changed by the owner outside this session."'
)


class DenyCauseTests(unittest.TestCase):
    """Each hand-rolled Codex deny emitter flags telemetry; stdout and exit code are byte-stable."""

    def run_hook(self, name: str, payload: Mapping[str, object], data: str) -> tuple[int, str, list[str]]:
        """Run a hook as a real process and return exit code, stdout and recorded causes."""
        env = {**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": data, "PLUGIN_DATA": data}
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

            code, out, causes = run("cat .codex/config.toml")
            self.assertEqual((code, out, causes), (0, ENVELOPE.format(rest=OWNER), ["deny"]))
            code, out, causes = run("git reset " + "--hard")
            self.assertEqual((code, causes[1:]), (0, ["deny"]))
            self.assertIn('"patternId"', out)
            code, out, causes = run("git status")
            self.assertEqual((code, out, causes[2:]), (0, "", ["ok"]))

    def test_verification_volume_ceiling(self) -> None:
        """Test the third full-suite run records deny; the first records ok."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"tool_input": {"command": "python3 hooks/scripts/tests/run_all.py"}, "cwd": tmp}
            code, out, causes = self.run_hook("verification_volume_ceiling", payload, tmp)
            self.assertEqual((code, out, causes), (0, "", ["ok"]))
            self.run_hook("verification_volume_ceiling", payload, tmp)
            code, out, causes = self.run_hook("verification_volume_ceiling", payload, tmp)
            reason = (
                "This is run 3 of the same full-suite on branch 'no-branch'. The third and later full "
                "re-runs are blocked; use a focused check or delegate verification with spawn_agent."
            )
            expected = ENVELOPE.format(rest=f'"permissionDecisionReason": {json.dumps(reason)}')
            self.assertEqual((code, out, causes[2:]), (0, expected, ["deny"]))

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
