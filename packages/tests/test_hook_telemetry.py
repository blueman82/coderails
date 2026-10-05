"""Content-free hook telemetry: exit causes, native-signal detection, bounded fds on both providers."""

from __future__ import annotations

import errno
import importlib
import json
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
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
        """Test resource exception is recorded then re-raised, never converted to success."""

        def boom() -> int:
            raise OSError(errno.EMFILE, "Too many open files")

        with patch("sys.stderr"), self.assertRaises(OSError):
            tel.run("h", boom)
        row = rows(self.dir)[0]
        self.assertEqual((row["cause"], row["exit"], row["errno"]), ("resource", 1, "EMFILE"))

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
        # A synthetic -SIGABRT returncode: really aborting a child would drop a crash report on macOS.
        self.assertEqual(tel.classify_returncode(-6), "native_signal")
        with patch.object(sys, "platform", "darwin"):
            tel.note_child("h", -6)
        row = rows(self.dir)[0]
        self.assertEqual((row["cause"], row["signal"]), ("native_signal", "SIGABRT"))
        self.assertIn("DiagnosticReports", row["diagnostic_hint"])

    def test_positive_child_exit_not_a_native_signal(self) -> None:
        """Test positive child exit not a native signal."""
        tel.note_child("h", 1)
        self.assertEqual(rows(self.dir), [])

    def test_sigterm_records_sigterm_flushes_stdout_and_exits_143(self) -> None:
        """Test sigterm is named as sigterm, not timeout; buffered decision output survives; exit is 143."""
        code = (
            f"import os,signal,sys;sys.path.insert(0,{str(ROOT)!r});"
            "from hooks.scripts.lib import hook_telemetry as t;"
            "t.run('slow', lambda: print('DECISION', end='') or os.kill(os.getpid(), signal.SIGTERM) or 0)"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env={**os.environ, "CODERAILS_HOOK_TELEMETRY_DIR": self.dir},
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 143)
        self.assertEqual(proc.stdout, "DECISION")
        self.assertEqual(proc.stderr, "terminated by SIGTERM, likely hook timeout; action NOT gated\n")
        self.assertEqual(rows(self.dir)[0]["cause"], "sigterm")

    def test_resource_errnos_classified_and_other_oserror_is_not(self) -> None:
        """Test every resource errno is a resource row; an unrelated OSError is an exception row."""
        for number in (errno.EMFILE, errno.ENFILE, errno.EAGAIN, errno.ENOMEM):
            with self.subTest(errno.errorcode[number]):

                def boom(number: int = number) -> int:
                    raise OSError(number, "x")

                with patch("sys.stderr"), self.assertRaises(OSError):
                    tel.run("h", boom)
                row = rows(self.dir)[-1]
                self.assertEqual((row["cause"], row["errno"]), ("resource", errno.errorcode[number]))

        def other() -> int:
            raise OSError(errno.ENOENT, "x")

        with self.assertRaises(OSError):
            tel.run("h", other)
        row = rows(self.dir)[-1]
        self.assertEqual((row["cause"], row["error"]), ("exception", "FileNotFoundError"))
        self.assertNotIn("errno", row)

    def test_record_never_raises_even_without_a_home(self) -> None:
        """Test Path.home() RuntimeError (no home directory) is swallowed."""
        env = {"CODERAILS_HOOK_TELEMETRY_DIR": "", "PLUGIN_DATA": ""}
        with patch.dict(os.environ, env), patch.object(Path, "home", side_effect=RuntimeError), patch("sys.stderr"):
            tel.record("h", "ok")

    def test_write_failure_emits_one_content_free_stderr_line(self) -> None:
        """Test a failed telemetry write says class and errno only."""
        with patch.dict(os.environ, {"CODERAILS_HOOK_TELEMETRY_DIR": "/dev/null/x"}), patch("sys.stderr") as err:
            tel.record("h", "ok")
        printed = "".join(call.args[0] for call in err.write.call_args_list)
        self.assertEqual(printed, "hook_telemetry: write failed (NotADirectoryError, errno=ENOTDIR)\n")

    def test_default_dir_follows_provider_home(self) -> None:
        """Test the Codex copy defaults under the Codex data home, the Claude copy under ~/.claude."""
        names = ("CODERAILS_HOOK_TELEMETRY_DIR", "CLAUDE_DISCIPLINE_LOG", "CODERAILS_DISCIPLINE_LOG", "PLUGIN_DATA")
        env = {key: value for key, value in os.environ.items() if key not in names}
        for path, expected in ((CLAUDE_LIB, ".claude"), (CODEX_LIB, ".coderails/codex")):
            module = runpy.run_path(str(path))
            with patch.dict(os.environ, env, clear=True), patch.object(Path, "home", return_value=Path("/h")):
                self.assertEqual(module["telemetry_dir"](), Path("/h") / expected)

    @staticmethod
    def exiting(code: int) -> Callable[[], int]:
        """Build a main() that exits with code."""

        def main() -> int:
            raise SystemExit(code)

        return main

    def test_gate_block_is_distinguishable_from_failure(self) -> None:
        """Test exit 2 records block while other non-zero exits record exit."""
        for code, cause in ((2, "block"), (1, "exit")):
            with self.assertRaises(SystemExit):
                tel.run("h", self.exiting(code))
            self.assertEqual(rows(self.dir)[-1]["cause"], cause)

    def test_extra_fields_are_allow_listed(self) -> None:
        """Test record drops any extra key that is not on the content-free allow-list."""
        tel.record("h", "ok", prompt="secret prompt", signal="SIGABRT")
        row = rows(self.dir)[0]
        self.assertNotIn("prompt", row)
        self.assertEqual(row["signal"], "SIGABRT")

    def test_diagnostic_hint_only_on_macos(self) -> None:
        """Test the macOS crash-report hint is omitted on other platforms."""
        with patch.object(sys, "platform", "linux"):
            tel.note_child("h", -6)
        self.assertNotIn("diagnostic_hint", rows(self.dir)[0])

    def test_log_rotates_past_cap(self) -> None:
        """Test the telemetry log rotates once instead of growing forever."""
        path = Path(self.dir) / "hook_telemetry.jsonl"
        path.write_text("x" * (tel.MAX_BYTES + 1))
        tel.record("h", "ok")
        self.assertTrue(path.with_suffix(".jsonl.1").exists())
        self.assertEqual(len(rows(self.dir)), 1)

    def test_record_is_fd_neutral_in_process(self) -> None:
        """Test 100 in-process runs do not accumulate descriptors, and a leaky main would be seen."""
        before = tel.open_fds()
        for _ in range(100):
            tel.run("h", lambda: 0)
        self.assertLessEqual(tel.open_fds() or 0, (before or 0) + 1)
        leaked: list[Any] = []

        def leaky() -> int:
            leaked.append(open(os.devnull))  # noqa: SIM115
            return 0

        tel.run("leaky", leaky)
        self.addCleanup(leaked[0].close)
        self.assertGreater(tel.open_fds() or 0, before or 0)

    def test_every_entrypoint_is_wrapped_with_a_guarded_import(self) -> None:
        """Test hook entrypoints run through telemetry and survive a missing telemetry module."""
        exempt = {"loop_dispatch_guard", "test_output", "voice_announce"}  # lane-A / CLI / detached
        for base in (ROOT / "hooks/scripts", ROOT / "packages/codex/hooks/scripts"):
            for path in sorted(base.glob("*.py")):
                text = path.read_text()
                codex_wiki = path.name == "wiki_taxonomy_gate.py" and "codex" in str(base)
                if "__main__" not in text or path.stem in exempt or codex_wiki:
                    continue
                with self.subTest(str(path.relative_to(ROOT))):
                    self.assertIn("except ImportError", text)
                    self.assertIn(f'run("{path.stem}", main)', text)

    def test_claude_call_sites_record_native_signal_children(self) -> None:
        """Test a signal-killed git child inside a Claude hook leaves a native_signal row."""
        inject_context: Any = importlib.import_module("hooks.scripts.inject_context")
        killed = subprocess.CompletedProcess([], -6, stdout="", stderr="")
        with patch.object(inject_context.subprocess, "run", return_value=killed):
            self.assertEqual(inject_context.git_branch("."), "none")
        row = rows(self.dir)[0]
        self.assertEqual((row["hook"], row["cause"], row["signal"]), ("inject_context", "native_signal", "SIGABRT"))


class StopHookSmokeTests(unittest.TestCase):
    """Each Stop hook, run as a real process, exits cleanly and leaves exactly one ok row per invocation."""

    runs = 3

    def check(self, script: Path) -> None:
        """Fire one hook a few times against an empty home; assert exit codes and rows."""
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
            for _ in range(self.runs):
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    input='{"hook_event_name":"Stop","session_id":"s"}',
                    text=True,
                    capture_output=True,
                    env=env,
                    timeout=30,
                )
                self.assertEqual(proc.returncode, 0, f"{script.name}: {proc.stderr}")
            got = rows(tmp)
            self.assertEqual([r["cause"] for r in got], ["ok"] * self.runs, script.name)
            self.assertEqual({r["hook"] for r in got}, {script.stem})

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

    def test_hook_common_errno_set_matches_telemetry(self) -> None:
        """Test hook_common and telemetry classify the same errnos as host exhaustion."""
        hook_common: Any = importlib.import_module("hooks.scripts.hook_common")

        self.assertEqual(hook_common.RESOURCE_ERRNOS, tel.RESOURCE_ERRNOS)

    def test_read_payload_raises_on_exhaustion_but_not_on_empty_input(self) -> None:
        """Test exhaustion is distinguishable from an empty payload."""
        hook_common: Any = importlib.import_module("hooks.scripts.hook_common")

        with patch("sys.stdin") as stdin, patch.object(hook_common, "log") as log:
            stdin.fileno.side_effect = OSError(errno.EMFILE, "Too many open files")
            with self.assertRaises(hook_common.HostResourceError):
                hook_common.read_payload()
        self.assertIn("resource_exhausted", log.call_args[0][0])
        with patch("sys.stdin") as stdin:
            stdin.fileno.side_effect = OSError(errno.EBADF, "bad")
            self.assertEqual(hook_common.read_payload(), {})

    def test_every_resource_errno_raises(self) -> None:
        """Test ENFILE, EAGAIN and ENOMEM are exhaustion too, not just EMFILE."""
        hook_common: Any = importlib.import_module("hooks.scripts.hook_common")

        for number in (errno.ENFILE, errno.EAGAIN, errno.ENOMEM):
            with self.subTest(errno.errorcode[number]), patch("sys.stdin") as stdin, patch.object(hook_common, "log"):
                stdin.fileno.side_effect = OSError(number, "x")
                with self.assertRaises(hook_common.HostResourceError):
                    hook_common.read_payload()

    def test_blocking_io_error_is_retried_not_exhaustion(self) -> None:
        """Test a transient EAGAIN from os.read keeps reading the payload instead of raising."""
        hook_common: Any = importlib.import_module("hooks.scripts.hook_common")
        reader, writer = os.pipe()
        os.write(writer, b'{"a": 1}')
        os.close(writer)
        self.addCleanup(os.close, reader)
        real_read = os.read
        pending = [BlockingIOError(errno.EAGAIN, "again")]

        def flaky(descriptor: int, size: int) -> bytes:
            if pending:
                raise pending.pop()
            return real_read(descriptor, size)

        with patch("sys.stdin") as stdin, patch.object(hook_common.os, "read", flaky):
            stdin.fileno.return_value = reader
            self.assertEqual(hook_common.read_payload(), {"a": 1})


if __name__ == "__main__":
    unittest.main()
