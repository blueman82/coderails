"""Content-free hook telemetry: exit causes, native-signal detection, bounded fds on both providers."""

from __future__ import annotations

import errno
import importlib
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
CLAUDE_LIB = ROOT / "hooks/scripts/lib/hook_telemetry.py"
CODEX_LIB = ROOT / "packages/codex/hooks/scripts/lib/hook_telemetry.py"
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import hook_telemetry as tel  # noqa: E402

CLAUDE_STOP = [
    "check_confidence_labels",
    "check_verify_loop",
    "loop_state_guard",
    "loop_stall_guard",
    "unregistered_loop_guard",
    "offload_push_guard",
]
CODEX_STOP = ["graph_completion_guard", "check_confidence_labels"]


def rows(directory: str) -> list[dict[str, Any]]:
    """Read the telemetry rows written under a directory."""
    path = Path(directory) / "hook_telemetry.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


class TelemetryTests(unittest.TestCase):
    """Row shape and exit-cause classification."""

    def setUp(self) -> None:
        """Point telemetry at a temp dir."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        env = patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": self.dir})
        env.start()
        self.addCleanup(env.stop)

    def test_providers_share_one_module(self) -> None:
        """Test providers share one module."""
        self.assertEqual(CLAUDE_LIB.read_bytes(), CODEX_LIB.read_bytes())

    def test_ok_row_is_content_free(self) -> None:
        """Test ok row is content free."""
        self.assertEqual(tel.run("h", lambda: 0), 0)
        (row,) = rows(self.dir)
        self.assertEqual((row["hook"], row["cause"], row["exit"]), ("h", "ok", 0))
        self.assertEqual(set(row), {"ts", "hook", "cause", "exit", "duration_ms", "open_fds", "pid"})

    def test_resource_exception_is_classified_not_swallowed(self) -> None:
        """Test resource exception is classified not swallowed."""

        def boom() -> int:
            raise OSError(errno.EMFILE, "Too many open files")

        with patch("sys.stderr"):
            self.assertEqual(tel.run("h", boom), 0)
        self.assertEqual(rows(self.dir)[0]["cause"], "resource")

    def test_other_exception_recorded_and_reraised(self) -> None:
        """Test other exception recorded and reraised."""

        def boom() -> int:
            raise ValueError("secret prompt text")

        with self.assertRaises(ValueError):
            tel.run("h", boom)
        row = rows(self.dir)[0]
        self.assertEqual(row["cause"], "exception")
        self.assertNotIn("secret", json.dumps(row))

    def test_write_failure_never_breaks_hook(self) -> None:
        """Test write failure never breaks hook."""
        with patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": "/dev/null/x"}):
            self.assertEqual(tel.run("h", lambda: 2), 2)

    def test_native_signal_child_detected_with_diagnostic_hint(self) -> None:
        """Test native signal child detected with diagnostic hint."""
        proc = subprocess.run([sys.executable, "-c", "import os,signal;os.kill(os.getpid(),signal.SIGABRT)"])
        self.assertEqual(tel.classify_returncode(proc.returncode), "native_signal")
        tel.note_child("h", proc.returncode)
        row = rows(self.dir)[0]
        self.assertEqual((row["cause"], row["signal"]), ("native_signal", "SIGABRT"))
        self.assertIn("DiagnosticReports", row["diagnostic_hint"])

    def test_positive_child_exit_not_a_native_signal(self) -> None:
        """Test positive child exit not a native signal."""
        tel.note_child("h", 1)
        self.assertEqual(rows(self.dir), [])

    def test_sigterm_records_timeout(self) -> None:
        """Test sigterm records timeout."""
        code = (
            f"import os,signal,sys;sys.path.insert(0,{str(ROOT)!r});"
            "from hooks.scripts.lib import hook_telemetry as t;"
            "t.run('slow', lambda: os.kill(os.getpid(), signal.SIGTERM) or 0)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], env={**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": self.dir}
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(rows(self.dir)[0]["cause"], "timeout")


class StopHookStressTests(unittest.TestCase):
    """Each Stop hook fired 100x (fresh process each) keeps its recorded fd count bounded."""

    def check(self, script: Path) -> None:
        """Fire one hook 100 times and bound its recorded fd count."""
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                **os.environ,
                "CODERAILS_HOOK_TELEMETRY_DIR": tmp,
                "CLAUDE_DISCIPLINE_LOG": f"{tmp}/d.log",
                "CODERAILS_DISCIPLINE_LOG": f"{tmp}/d.log",
                "CLAUDE_AGENTIC_LOOP_DIR": f"{tmp}/loops",
                "PLUGIN_DATA": tmp,
                "HOME": tmp,
            }
            for _ in range(100):
                subprocess.run(
                    [sys.executable, str(script)],
                    input='{"hook_event_name":"Stop","session_id":"s"}',
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=30,
                )
            fds = [r["open_fds"] for r in rows(tmp)]
            self.assertEqual(len(fds), 100, script.name)
            self.assertLessEqual(max(fds), min(fds) + 2, script.name)
            self.assertLess(max(fds), 16, script.name)

    def test_claude_stop_hooks(self) -> None:
        """Test claude stop hooks."""
        for name in CLAUDE_STOP:
            with self.subTest(name):
                self.check(ROOT / "hooks/scripts" / f"{name}.py")

    def test_codex_stop_hooks(self) -> None:
        """Test codex stop hooks."""
        for name in CODEX_STOP:
            with self.subTest(name):
                self.check(ROOT / "packages/codex/hooks/scripts" / f"{name}.py")


class ClaudeResourceClassificationTests(unittest.TestCase):
    """Claude hook_common mirrors the Codex EMFILE classification."""

    def test_hook_common_exposes_resource_classification(self) -> None:
        """Test hook common exposes resource classification."""
        hook_common: Any = importlib.import_module("hooks.scripts.hook_common")

        self.assertIn(errno.EMFILE, hook_common.RESOURCE_ERRNOS)
        self.assertEqual(hook_common.HostResourceError.__mro__[1], OSError)

    def test_read_payload_reports_resource_errno(self) -> None:
        """Test read payload reports resource errno."""
        hook_common: Any = importlib.import_module("hooks.scripts.hook_common")

        with patch("sys.stdin") as stdin, patch.object(hook_common, "log") as log:
            stdin.fileno.side_effect = OSError(errno.EMFILE, "Too many open files")
            self.assertEqual(hook_common.read_payload(), {})
        self.assertIn("resource exhaustion", log.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
