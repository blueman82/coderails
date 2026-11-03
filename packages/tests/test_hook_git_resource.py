"""Git lookup resource errors must reach the hook as a denial."""

from __future__ import annotations

import contextlib
import errno
import importlib
import io
import json
import sys
import unittest
from itertools import product
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
claude_gate = importlib.import_module("hooks.scripts.destructive_bash_gate")
claude_patterns = importlib.import_module("hooks.scripts.lib.destructive_patterns")
claude_test_gate = importlib.import_module("hooks.scripts.test_gate")
claude_authority = importlib.import_module("hooks.scripts.action_authority_gate")
sys.path.insert(0, str(ROOT / "packages/codex/hooks/scripts"))
codex_gate = importlib.import_module("destructive_bash_gate")
codex_patterns = importlib.import_module("lib.destructive_patterns")
codex_test_gate = importlib.import_module("test_gate")
codex_authority = importlib.import_module("action_authority_gate")


class GitResourceTests(unittest.TestCase):
    """A host error is not an empty branch or an allowed command."""

    def test_authority_hooks_deny_resource_errors_before_policy_discovery(self) -> None:
        """Resource exhaustion cannot pass a protected push before enforcement is known."""
        payload = {"session_id": "inert-owner", "tool_input": {"command": "git push origin main"}, "cwd": "/tmp"}
        for gate, patterns, reader, tracer in (
            (claude_authority, claude_patterns, "read_payload_strict", "append_row"),
            (codex_authority, codex_patterns, "read_input", "append_trace_row"),
        ):
            for code in (errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENOMEM):
                with self.subTest(gate=gate.__name__, errno=code):
                    output, errors = io.StringIO(), io.StringIO()
                    value = payload if gate is claude_authority else json.dumps(payload)
                    with (
                        patch.object(gate, reader, return_value=value),
                        patch.object(gate, "resolve_mode", return_value=("enforce", False)) as policy,
                        patch.object(gate, "read_authority") as authority,
                        patch.object(gate, tracer) as trace,
                        patch.object(patterns.subprocess, "run", side_effect=OSError(code, "inert exhaustion")),
                        contextlib.redirect_stdout(output),
                        contextlib.redirect_stderr(errors),
                    ):
                        self.assertEqual(gate.main(), 0)
                    policy.assert_not_called()
                    authority.assert_not_called()
                    self.assertTrue(output.getvalue(), errors.getvalue())
                    decision = json.loads(output.getvalue())["hookSpecificOutput"]
                    self.assertEqual(decision["permissionDecision"], "deny")
                    self.assertIn("resource exhaustion", decision["permissionDecisionReason"])
                    self.assertEqual(trace.call_args.args[1:3], ("denied", "denied_gate_error"))
                    self.assertNotIn("failed open", errors.getvalue())

    def test_authority_known_policy_errors_preserve_off_and_advisory_policy(self) -> None:
        """Known policy applies to both resource and ordinary errors after authority discovery."""
        payload = {"session_id": "inert-owner", "tool_input": {"command": "git push origin main"}, "cwd": "/tmp"}
        providers = (
            (claude_authority, "read_payload_strict", "append_row"),
            (codex_authority, "read_input", "append_trace_row"),
        )
        cases = (("off", True, False), ("advisory", False, False), ("advisory", True, True), ("enforce", False, True))
        failures = (RuntimeError("inert ordinary error"), OSError(errno.EMFILE, "inert resource error"))
        for (gate, reader, tracer), (mode, live, denied), failure in product(providers, cases, failures):
            call = gate.Operation("git_push", "git push origin main", "/tmp", "/tmp", [], ["origin", "main"], "/tmp")
            with self.subTest(gate=gate.__name__, mode=mode, live=live, failure=type(failure).__name__):
                output, errors = io.StringIO(), io.StringIO()
                value = payload if gate is claude_authority else json.dumps(payload)
                with (
                    patch.object(gate, reader, return_value=value),
                    patch.object(gate, "guarded_operations", return_value=[call]),
                    patch.object(gate, "repository", return_value="/tmp"),
                    patch.object(gate, "config_path", return_value=None),
                    patch.object(gate, "resolve_mode", return_value=(mode, False)),
                    patch.object(gate, "read_authority", return_value={"loop_id": "inert"} if live else None),
                    patch.object(gate, "resolve_trust_root", return_value=(None, "user")),
                    patch.object(gate, "check_action_modes", side_effect=failure),
                    patch.object(gate, tracer),
                    contextlib.redirect_stdout(output),
                    contextlib.redirect_stderr(errors),
                ):
                    self.assertEqual(gate.main(), 0)
                self.assertEqual(bool(output.getvalue()), denied)

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
