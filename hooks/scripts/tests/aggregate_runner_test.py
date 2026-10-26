"""Check aggregate discovery, skip accounting and Git isolation using inert suites."""

from __future__ import annotations

import contextlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.run_all import isolated_environment, run_suites


class AggregateRunnerTests(unittest.TestCase):
    """Verify truthful suite accounting without invoking repository suites."""

    def test_empty_skip_and_mixed_results(self) -> None:
        """Require at least one executed success and no genuine failures."""
        with (
            tempfile.TemporaryDirectory() as temporary,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            directory = Path(temporary)
            self.assertEqual(run_suites(directory), 1)
            (directory / "skip_test.py").write_text("raise SystemExit(3)\n")
            self.assertEqual(run_suites(directory), 1)
            (directory / "pass_test.py").write_text("raise SystemExit(0)\n")
            self.assertEqual(run_suites(directory), 0)
            (directory / "failure_test.py").write_text("raise SystemExit(2)\n")
            self.assertEqual(run_suites(directory), 1)

    def test_skip_output_and_neighbouring_failure_codes(self) -> None:
        """Name skips honestly and never absorb exits immediately above or below three."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "skip_test.py").write_text("raise SystemExit(3)\n")
            (directory / "pass_test.py").write_text("raise SystemExit(0)\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_suites(directory), 0)
            self.assertIn("SKIPPED (prerequisite): skip_test.py", output.getvalue())
            self.assertIn("1 skipped", output.getvalue())
            (directory / "skip_test.py").unlink()
            for code in (1, 2, 4):
                (directory / "failure_test.py").write_text(f"raise SystemExit({code})\n")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(run_suites(directory), 1)
                self.assertIn(f"FAILED (exit {code})", output.getvalue())
                self.assertNotIn("SKIPPED", output.getvalue())

    def test_unretired_suite_refuses_partial_coverage(self) -> None:
        """A Python-only runner cannot advertise success while old suites remain."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            directory = Path(temporary)
            (directory / "pass_test.py").write_text("raise SystemExit(0)\n")
            (directory / "unretired.test.sh").write_text("exit 1\n")
            self.assertEqual(run_suites(directory), 1)

    def test_worker_error_is_a_named_failure(self) -> None:
        """An executor error cannot remove a suite from the final count."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "broken_test.py").write_text("raise SystemExit(0)\n")
            output = io.StringIO()

            def broken(*args: object) -> None:
                assert isinstance(args[-1], Path)
                args[-1].write_text("partial output\n")
                raise RuntimeError("worker lost")

            with (
                patch("hooks.scripts.tests.run_all._run_one", side_effect=broken),
                contextlib.redirect_stdout(output),
            ):
                self.assertEqual(run_suites(directory), 1)
            self.assertIn("=== broken_test.py ===", output.getvalue())
            self.assertIn("partial output", output.getvalue())
            self.assertIn("Suite runner failed: worker lost", output.getvalue())
            self.assertIn("0/1 suites passed", output.getvalue())

    def test_git_environment_removed(self) -> None:
        """Scrub every indexed override, preserving unrelated process settings."""
        with patch.dict(
            os.environ,
            {"GIT_DIR": "/wrong", "GIT_CONFIG_KEY_17": "bad", "GIT_CONFIG_VALUE_17": "bad", "KEEP_THIS": "yes"},
        ):
            environment = isolated_environment()
            self.assertNotIn("GIT_DIR", environment)
            self.assertNotIn("GIT_CONFIG_KEY_17", environment)
            self.assertNotIn("GIT_CONFIG_VALUE_17", environment)
            self.assertEqual(environment["KEEP_THIS"], "yes")

    def test_parallel_suites_keep_complete_labelled_output(self) -> None:
        """Two suites must overlap and keep their stdout and stderr under their own names."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name, peer in (("alpha", "beta"), ("beta", "alpha")):
                (directory / f"{name}_test.py").write_text(
                    "import pathlib, sys, time\n"
                    f"pathlib.Path({str(directory / name)!r}).touch()\n"
                    f"peer = pathlib.Path({str(directory / peer)!r})\n"
                    "for _ in range(300):\n"
                    "    if peer.exists():\n"
                    "        break\n"
                    "    time.sleep(0.01)\n"
                    "else:\n"
                    "    raise SystemExit(2)\n"
                    f"print({name!r})\n"
                    f"print({name + '-error'!r}, file=sys.stderr)\n",
                    encoding="utf-8",
                )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_suites(directory), 0)
            text = output.getvalue()
            self.assertEqual(text.count("=== alpha_test.py ==="), 1)
            self.assertEqual(text.count("=== beta_test.py ==="), 1)
            for marker in ("alpha\n", "alpha-error\n", "beta\n", "beta-error\n"):
                self.assertIn(marker, text)
            self.assertLess(text.index("PASS alpha_test.py"), text.index("PASS beta_test.py"))

    def test_large_output_keeps_split_unicode_character(self) -> None:
        """Disk capture and text replay keep a character across read chunks."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "large_test.py").write_text(
                "import sys\nsys.stdout.buffer.write(b'a' * 65535 + 'é'.encode())\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_suites(directory), 0)
            self.assertIn("a" * 65535 + "é", output.getvalue())

    def test_timeout_fails_and_stops_the_suite(self) -> None:
        """A timed-out suite cannot pass or leave its process running."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            pid_file = directory / "pid"
            (directory / "wait_test.py").write_text(
                f"import os, pathlib, time\npathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
                "time.sleep(10)\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_suites(directory, jobs=1, suite_timeout=0.5), 1)
            self.assertIn("Suite timed out", output.getvalue())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)

    def test_suite_exit_stops_descendant(self) -> None:
        """A finished suite cannot leave its detached child running."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            marker = directory / "late"
            child = f"import time, pathlib; time.sleep(0.8); pathlib.Path({str(marker)!r}).touch()"
            (directory / "wait_test.py").write_text(
                "import subprocess, sys\n" + f"subprocess.Popen([sys.executable, '-c', {child!r}])\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            started = time.monotonic()
            with contextlib.redirect_stdout(output):
                result = run_suites(directory, jobs=1, suite_timeout=2)
            self.assertEqual(result, 0, output.getvalue())
            self.assertLess(time.monotonic() - started, 2)
            time.sleep(1)
            self.assertFalse(marker.exists())

    def test_interrupt_stops_active_suite(self) -> None:
        """SIGINT and SIGTERM both stop the active test process group."""
        for kind in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                pid_file = directory / "pid"
                (directory / "wait_test.py").write_text(
                    "import os, pathlib, time\nprint('CHILD_EVIDENCE', flush=True)\n"
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
                    "time.sleep(10)\n",
                    encoding="utf-8",
                )
                root = Path(__file__).resolve().parents[3]
                program = (
                    f"import sys; sys.path.insert(0, {str(root)!r}); "
                    "from pathlib import Path; from hooks.scripts.tests.run_all import run_suites; "
                    "raise SystemExit(run_suites(Path(sys.argv[1]), jobs=1))"
                )
                runner = subprocess.Popen(
                    [sys.executable, "-c", program, str(directory)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                try:
                    for _ in range(300):
                        if pid_file.exists() and pid_file.read_text():
                            break
                        time.sleep(0.01)
                    else:
                        self.fail("suite did not start")
                    runner.send_signal(kind)
                    output, _ = runner.communicate(timeout=5)
                    self.assertEqual(runner.returncode, 130, output.decode(errors="replace"))
                    self.assertIn("CHILD_EVIDENCE", output.decode(errors="replace"))
                    with self.assertRaises(ProcessLookupError):
                        os.kill(int(pid_file.read_text()), 0)
                finally:
                    if runner.poll() is None:
                        runner.kill()
                        runner.communicate()


if __name__ == "__main__":
    unittest.main()
