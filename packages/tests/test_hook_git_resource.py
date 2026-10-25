"""Git lookup resource errors must reach the hook as a denial."""

from __future__ import annotations

import contextlib
import errno
import importlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
claude_gate = importlib.import_module("hooks.scripts.destructive_bash_gate")
claude_patterns = importlib.import_module("hooks.scripts.lib.destructive_patterns")
claude_test_gate = importlib.import_module("hooks.scripts.test_gate")
sys.path.insert(0, str(ROOT / "packages/codex/hooks/scripts"))
codex_gate = importlib.import_module("destructive_bash_gate")
codex_patterns = importlib.import_module("lib.destructive_patterns")
codex_test_gate = importlib.import_module("test_gate")


class GitResourceTests(unittest.TestCase):
    """A host error is not an empty branch or an allowed command."""

    def test_git_output_raises_for_resource_errors(self) -> None:
        """Both providers distinguish EMFILE from an ordinary missing Git binary."""
        for module in (claude_patterns, codex_patterns):
            with self.subTest(module=module.__name__):
                with (
                    patch.object(module.subprocess, "run", side_effect=OSError(errno.EMFILE, "exhausted")),
                    self.assertRaises(OSError) as caught,
                ):
                    module.git_output("/tmp", "branch", "--show-current")
                self.assertEqual(caught.exception.errno, errno.EMFILE)
                with patch.object(module.subprocess, "run", side_effect=FileNotFoundError(errno.ENOENT, "git absent")):
                    self.assertEqual(module.git_output("/tmp", "branch", "--show-current"), "")

    def test_destructive_hooks_deny_when_git_lookup_exhausts(self) -> None:
        """The force-with-lease allowance cannot be inferred from a failed Git lookup."""
        payload = {"tool_input": {"command": "git push --force-with-lease origin feature"}, "cwd": "/tmp"}
        for gate, patterns, reader in (
            (claude_gate, claude_patterns, "read_payload_strict"),
            (codex_gate, codex_patterns, "read_input"),
        ):
            with self.subTest(gate=gate.__name__):
                output = io.StringIO()
                value = payload if gate is claude_gate else json.dumps(payload)
                with (
                    patch.object(gate, reader, return_value=value),
                    patch.object(patterns.subprocess, "run", side_effect=OSError(errno.EMFILE, "exhausted")),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(gate.main(), 0)
                decision = json.loads(output.getvalue())["hookSpecificOutput"]
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertIn("resource exhaustion", decision["permissionDecisionReason"])

    def test_commit_hooks_deny_when_git_lookup_exhausts(self) -> None:
        """A commit does not pass when its test-command path cannot be resolved."""
        payload = {"tool_input": {"command": "git commit -m x"}, "cwd": "/tmp"}
        for gate, patterns, reader in (
            (claude_test_gate, claude_patterns, "read_payload"),
            (codex_test_gate, codex_patterns, "read_input"),
        ):
            with self.subTest(gate=gate.__name__):
                output = io.StringIO()
                with (
                    patch.object(gate, reader, return_value=json.dumps(payload)),
                    patch.object(patterns.subprocess, "run", side_effect=OSError(errno.EMFILE, "exhausted")),
                    contextlib.redirect_stdout(output),
                ):
                    self.assertEqual(gate.main(), 0)
                decision = json.loads(output.getvalue())["hookSpecificOutput"]
                self.assertEqual(decision["permissionDecision"], "deny")
                self.assertIn("resource exhaustion", decision["permissionDecisionReason"])


if __name__ == "__main__":
    unittest.main()
