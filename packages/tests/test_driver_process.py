"""A timed-out or interrupted driver worker is never launched twice."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "graph-semantics"))
import graph_driver_process  # noqa: E402


class DriverProcessTests(unittest.TestCase):
    """Exercise a real child process and durable attempt files."""

    def test_timeout_keeps_live_worker_and_refuses_duplicate_launch(self) -> None:
        """A poll timeout leaves the worker alive and bars another launch."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path\nimport time\n"
                "while not Path('release').exists():\n    time.sleep(0.01)\n"
                "print('finished')\n",
            ]
            graph_driver_process.start(artifact, command, artifact)
            self.assertEqual(graph_driver_process.observe(artifact, 0.01)["status"], "running")
            with self.assertRaisesRegex(ValueError, "already"):
                graph_driver_process.start(artifact, command, artifact)
            (artifact / "release").touch()
            deadline = time.monotonic() + 5
            result: dict[str, object] = {"status": "unresolved"}
            while time.monotonic() < deadline:
                result = graph_driver_process.observe(artifact, 0.05)
                if result["status"] == "finished":
                    break
            self.assertEqual(result, {"status": "finished", "exit_code": 0})
            self.assertEqual((artifact / "output.jsonl").read_text().strip(), "finished")

    def test_denied_process_lookup_uses_owned_child_and_terminal_record(self) -> None:
        """A sandbox denial cannot crash observation or lose a completed worker."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            command = [sys.executable, "-c", "import time; time.sleep(2)"]
            graph_driver_process.start(artifact, command, artifact)
            with patch("graph_driver_process.subprocess.run", side_effect=PermissionError("ps denied")):
                self.assertEqual(graph_driver_process.observe(artifact, 0)["status"], "running")
                with patch.dict("graph_driver_process._CHILDREN", {}, clear=True):
                    self.assertEqual(graph_driver_process.observe(artifact, 0.5)["status"], "running")
            denied = subprocess.CompletedProcess(["ps"], 1, "", "permission denied")
            with (
                patch("graph_driver_process.subprocess.run", return_value=denied),
                patch.dict("graph_driver_process._CHILDREN", {}, clear=True),
            ):
                self.assertEqual(graph_driver_process.observe(artifact, 0.5)["status"], "running")
            deadline = time.monotonic() + 5
            result: dict[str, object] = {"status": "unresolved"}
            while time.monotonic() < deadline:
                result = graph_driver_process.observe(artifact, 0.05)
                if result["status"] == "finished":
                    break
            self.assertEqual(result, {"status": "finished", "exit_code": 0})

    def test_unresolved_launch_marker_never_relaunches(self) -> None:
        """An uncertain crash window must fail closed."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            (artifact / "launch.json").write_text(json.dumps({"status": "reserved"}))
            self.assertEqual(graph_driver_process.observe(artifact, 0)["status"], "unresolved")
            with self.assertRaisesRegex(ValueError, "already"):
                graph_driver_process.start(artifact, [sys.executable, "-c", "pass"], artifact)

    def test_stale_or_foreign_heartbeat_cannot_prove_a_worker_is_live(self) -> None:
        """A denied process lookup needs a fresh matching wrapper pulse."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            (artifact / "launch.json").write_text(json.dumps({"status": "started", "token": "owned", "pid": 42}))
            with patch("graph_driver_process.subprocess.run", side_effect=PermissionError("ps denied")):
                for pulse in (
                    {"token": "other", "pid": 42, "seen": time.time()},
                    {"token": "owned", "pid": 42, "seen": time.time() - 5},
                ):
                    (artifact / "heartbeat.json").write_text(json.dumps(pulse))
                    self.assertEqual(graph_driver_process.observe(artifact, 0)["status"], "unresolved")

    def test_second_controller_cannot_own_the_same_graph(self) -> None:
        """The process lease is separate from graph operation locks."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            with (
                graph_driver_process.lease(path),
                self.assertRaisesRegex(ValueError, "already"),
                graph_driver_process.lease(path),
            ):
                self.fail("second driver acquired the lease")

    def test_new_controller_observes_the_old_live_worker(self) -> None:
        """A new driver process finds a live worker from the first driver."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            module_dir = Path(graph_driver_process.__file__).parent
            worker = (
                "from pathlib import Path\nimport time\nwhile not Path('release').exists():\n    time.sleep(0.01)\n"
            )
            script = (
                "import sys\nfrom pathlib import Path\n"
                f"sys.path.insert(0, {str(module_dir)!r})\n"
                "import graph_driver_process\n"
                "path = Path(sys.argv[1])\n"
                f"graph_driver_process.start(path, [sys.executable, '-c', {worker!r}], path)\n"
            )
            launched = subprocess.run([sys.executable, "-c", script, str(artifact)], capture_output=True, text=True)
            self.assertEqual(launched.returncode, 0, launched.stderr)
            with patch("graph_driver_process.subprocess.run", side_effect=PermissionError("ps denied")):
                self.assertEqual(graph_driver_process.observe(artifact, 0.5)["status"], "running")
            with self.assertRaisesRegex(ValueError, "already"):
                graph_driver_process.start(artifact, [sys.executable, "-c", "pass"], artifact)
            (artifact / "release").touch()
            deadline = time.monotonic() + 5
            result: dict[str, object] = {"status": "unresolved"}
            while time.monotonic() < deadline:
                result = graph_driver_process.observe(artifact, 0.05)
                if result["status"] == "finished":
                    break
            self.assertEqual(result, {"status": "finished", "exit_code": 0})

    def test_failing_child_has_a_durable_terminal_code(self) -> None:
        """A child failure leaves a code that a new process can read."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            graph_driver_process.start(artifact, [sys.executable, "-c", "raise SystemExit(7)"], artifact)
            deadline = time.monotonic() + 5
            result: dict[str, object] = {"status": "unresolved"}
            while time.monotonic() < deadline:
                result = graph_driver_process.observe(artifact, 0.05)
                if result["status"] == "finished":
                    break
            self.assertEqual(result, {"status": "finished", "exit_code": 7})

    def test_child_stderr_stays_separate_from_output(self) -> None:
        """A failed Codex process leaves diagnostics without corrupting JSONL."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            command = [
                sys.executable,
                "-c",
                'import sys; print(\'{"type":"thread.started"}\'); '
                "print('codex-failure-marker', file=sys.stderr); raise SystemExit(7)",
            ]
            graph_driver_process.start(artifact, command, artifact)
            deadline = time.monotonic() + 5
            result: dict[str, object] = {"status": "unresolved"}
            while time.monotonic() < deadline:
                result = graph_driver_process.observe(artifact, 0.05)
                if result["status"] == "finished":
                    break
            self.assertEqual(result, {"status": "finished", "exit_code": 7})
            self.assertEqual((artifact / "output.jsonl").read_text().strip(), '{"type":"thread.started"}')
            self.assertIn("codex-failure-marker", (artifact / "stderr.log").read_text())

    def test_wrapper_failure_keeps_diagnostic_without_terminal(self) -> None:
        """A wrapper crash remains unresolved and records its Python error."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            (artifact / "launch.json.tmp").touch()
            self.assertEqual(
                graph_driver_process.start(artifact, [sys.executable, "-c", "pass"], artifact),
                {"status": "unresolved"},
            )
            self.assertFalse((artifact / "terminal.json").exists())
            self.assertIn("FileExistsError", (artifact / "stderr.log").read_text())

    def test_killed_wrapper_cannot_launch_the_same_attempt_again(self) -> None:
        """An orphaned child leaves a clear unresolved result and a reserved launch."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            command = [
                sys.executable,
                "-c",
                "from pathlib import Path\nimport time\nPath('active').touch()\n"
                "while not Path('release').exists():\n    time.sleep(0.01)\n",
            ]
            graph_driver_process.start(artifact, command, artifact)
            launch = json.loads((artifact / "launch.json").read_text())
            try:
                deadline = time.monotonic() + 5
                while not (artifact / "active").exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue((artifact / "active").exists())
                os.kill(launch["pid"], signal.SIGKILL)
                graph_driver_process._CHILDREN[launch["token"]].wait(timeout=5)  # pyright: ignore[reportPrivateUsage]
                time.sleep(1.1)
                self.assertEqual(
                    graph_driver_process.observe(artifact, 0.1),
                    {"status": "unresolved", "reason": "worker_identity_unconfirmed_terminal_missing"},
                )
                self.assertFalse((artifact / "terminal.json").exists())
                with self.assertRaisesRegex(ValueError, "already"):
                    graph_driver_process.start(artifact, command, artifact)
            finally:
                (artifact / "release").touch()
                child = graph_driver_process._CHILDREN.pop(launch["token"], None)  # pyright: ignore[reportPrivateUsage]
                if child is not None:
                    child.wait(timeout=5)

    def test_launch_failure_has_an_empty_output_artifact(self) -> None:
        """A failed wrapper launch still leaves sealable failed-attempt files."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            with patch("graph_driver_process.subprocess.Popen", side_effect=PermissionError("launch denied")):
                self.assertEqual(
                    graph_driver_process.start(artifact, [sys.executable, "-c", "pass"], artifact),
                    {"status": "finished", "exit_code": 127},
                )
            self.assertEqual(graph_driver_process.observe(artifact, 0), {"status": "finished", "exit_code": 127})
            self.assertEqual((artifact / "output.jsonl").read_bytes(), b"")
            self.assertEqual((artifact / "stderr.log").read_bytes(), b"")

    def test_worker_receives_prompt_and_private_environment(self) -> None:
        """The prompt enters on stdin and the environment stays out of process records."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            prompt = artifact / "prompt.txt"
            prompt.write_text("owned prompt\n")
            environment = {**os.environ, "CODERAILS_TEST_TOKEN": "disposable-marker"}
            worker = "import os, sys; print(sys.stdin.read().strip()); print(bool(os.getenv('CODERAILS_TEST_TOKEN')))"
            graph_driver_process.start(
                artifact, [sys.executable, "-c", worker], artifact, environment=environment, stdin_path=prompt
            )
            deadline = time.monotonic() + 5
            result: dict[str, object] = {"status": "unresolved"}
            while time.monotonic() < deadline:
                result = graph_driver_process.observe(artifact, 0.05)
                if result["status"] == "finished":
                    break
            self.assertEqual(result, {"status": "finished", "exit_code": 0})
            self.assertEqual((artifact / "output.jsonl").read_text().splitlines(), ["owned prompt", "True"])
            self.assertNotIn("disposable-marker", (artifact / "launch.json").read_text())
            self.assertNotIn("disposable-marker", (artifact / "terminal.json").read_text())

    def test_worker_receives_checked_bytes_after_prompt_file_changes(self) -> None:
        """The Codex worker must not reopen a mutable prompt after authorization."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            prompt = artifact / "prompt.txt"
            expected = "authorized café Ω\nsecond line\nterminal canary\n".encode()
            prompt.write_bytes(expected)
            graph_driver_process.start(
                artifact,
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
                artifact,
                stdin_bytes=expected,
            )
            prompt.write_bytes(b"changed prompt\n")
            for _attempt in range(100):
                if graph_driver_process.observe(artifact, 0.05)["status"] == "finished":
                    break
            self.assertEqual((artifact / "output.jsonl").read_bytes(), expected)


if __name__ == "__main__":
    unittest.main()
