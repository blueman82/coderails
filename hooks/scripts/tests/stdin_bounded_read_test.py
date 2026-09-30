#!/usr/bin/env python3
"""Verify orphaned-pipe deadlines and multiline payload fidelity through real hook processes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HOOKS, HookTestCase


class BoundedReadTests(HookTestCase):
    """An open producer cannot hold a hook beyond its five-second input budget."""

    def test_empty_and_partially_filled_open_pipes(self) -> None:
        """Each original representative exits on both idle pipes and pipes left open after bytes."""
        for name in ("test_gate", "check_confidence_labels", "unregistered_loop_guard"):
            for prefix in (b"", b'{"session_id": "partial",'):
                with self.subTest(hook=name, prefix=prefix):
                    read_fd, write_fd = os.pipe()
                    try:
                        if prefix:
                            os.write(write_fd, prefix)
                        start = time.monotonic()
                        process = subprocess.Popen(
                            [sys.executable, str(HOOKS / f"{name}.py")],
                            stdin=read_fd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            cwd=self.directory,
                            env=self.environment,
                        )
                        try:
                            output, error = process.communicate(timeout=7)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.communicate()
                            self.fail("hook exceeded the bounded input deadline")
                        self.assertLess(time.monotonic() - start, 6.5)
                        self.assertEqual(process.returncode, 0, error)
                        self.assertNotIn(b'"deny"', output)
                    finally:
                        os.close(read_fd)
                        os.close(write_fd)

    def test_multiline_decisions_and_empty_input(self) -> None:
        """Multiline parsing preserves real denial, safe allowance, and empty-input fail-open."""
        config = self.directory / ".claude/test_command"
        config.parent.mkdir()
        config.write_text("false\n")
        for name, command, denied in (
            ("test_gate", "git commit -m fix", True),
            ("destructive_bash_gate", "rm -rf /tmp/example", True),
            ("destructive_bash_gate", "git status", False),
        ):
            request = {"tool_name": "Bash", "tool_input": {"command": command}}
            result = subprocess.run(
                [sys.executable, str(HOOKS / f"{name}.py")],
                input=json.dumps(request, indent=2),
                text=True,
                capture_output=True,
                cwd=self.directory,
                env=self.environment,
                check=False,
            )
            self.assertEqual(result.returncode, 0)
            self.assertEqual('"deny"' in result.stdout, denied, result.stderr)
        result = subprocess.run(
            [sys.executable, str(HOOKS / "destructive_bash_gate.py")],
            input="",
            text=True,
            capture_output=True,
            env=self.environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        result = self.run_hook(
            "check_confidence_labels", {"transcript_path": "/nonexistent", "hook_event_name": "Stop"}
        )
        self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
