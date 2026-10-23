"""A timed-out or interrupted driver worker is never launched twice."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

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

    def test_unresolved_launch_marker_never_relaunches(self) -> None:
        """An uncertain crash window must fail closed."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            (artifact / "launch.json").write_text(json.dumps({"status": "reserved"}))
            self.assertEqual(graph_driver_process.observe(artifact, 0)["status"], "unresolved")
            with self.assertRaisesRegex(ValueError, "already"):
                graph_driver_process.start(artifact, [sys.executable, "-c", "pass"], artifact)

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
                "from pathlib import Path\nimport time\n" "while not Path('release').exists():\n    time.sleep(0.01)\n"
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
            self.assertEqual(graph_driver_process.observe(artifact, 0.01)["status"], "running")
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


if __name__ == "__main__":
    unittest.main()
