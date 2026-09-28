"""Verify dashboard PID ownership, termination and readiness without signalling real processes."""

import importlib
import io
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class DashboardProcessTests(unittest.TestCase):
    """Retain interactive start/stop behavior separately from foreground service startup."""

    def test_stop_identity_and_termination(self) -> None:
        """Never terminate a reused PID; retain failed state when a server survives KILL."""
        for prefix, home_name in (("skills.dashboard", ".claude"), ("packages.codex.skills.dashboard", ".codex")):
            module = importlib.import_module(f"{prefix}.scripts.stop_dashboard")
            for scenario in ("absent", "stale", "foreign", "stopped", "survived"):
                with self.subTest(prefix=prefix, scenario=scenario), tempfile.TemporaryDirectory() as directory:
                    home = Path(directory)
                    pid_file = home / home_name / "coderails-dashboard/dashboard.pid"
                    if scenario != "absent":
                        pid_file.parent.mkdir(parents=True)
                        pid_file.write_text("12345")
                    probes = [True, False, False, False] if scenario == "stopped" else None
                    output = io.StringIO()
                    with (
                        patch.dict(os.environ, {"HOME": directory}),
                        redirect_stdout(output),
                        patch.object(module, "alive", side_effect=probes, return_value=scenario != "stale"),
                        patch.object(module.os, "kill") as kill,
                        patch.object(module.time, "sleep"),
                        patch.object(
                            module.subprocess,
                            "run",
                            return_value=subprocess.CompletedProcess(
                                [], 0, "unrelated process" if scenario == "foreign" else "node next server"
                            ),
                        ),
                    ):
                        result = module.main()
                    if scenario in ("absent", "stale", "foreign"):
                        kill.assert_not_called()
                        self.assertEqual(result, 0)
                        self.assertFalse(pid_file.exists())
                    elif scenario == "stopped":
                        kill.assert_called_once_with(12345, signal.SIGTERM)
                        self.assertFalse(pid_file.exists())
                    else:
                        self.assertEqual(result, 1)
                        self.assertTrue(pid_file.exists())
                        self.assertEqual(
                            [call.args[1] for call in kill.call_args_list], [signal.SIGTERM, signal.SIGKILL]
                        )
                    expected = {
                        "absent": "not_running",
                        "stale": "stale_pid",
                        "foreign": "stale_pid",
                        "stopped": "stopped",
                        "survived": "failed",
                    }[scenario]
                    self.assertIn(f'"status": "{expected}"', output.getvalue())

    def test_readiness_owned_child_and_timeout(self) -> None:
        """A foreign successful curl response cannot hide an exited owned child."""
        for prefix in ("skills.dashboard", "packages.codex.skills.dashboard"):
            module = importlib.import_module(f"{prefix}.scripts.start_dashboard")
            for scenario in ("early", "after", "timeout", "ready"):
                with self.subTest(prefix=prefix, scenario=scenario), tempfile.TemporaryDirectory() as directory:
                    pid_file, log = Path(directory) / "pid", Path(directory) / "log"
                    pid_file.write_text("12345")
                    child = Mock()
                    child.poll.side_effect = [1] if scenario == "early" else [None, 1] if scenario == "after" else None
                    child.poll.return_value = None
                    with (
                        patch.object(module.time, "sleep"),
                        patch.object(
                            module.subprocess,
                            "run",
                            return_value=subprocess.CompletedProcess([], 1 if scenario == "timeout" else 0),
                        ),
                    ):
                        if scenario == "ready":
                            module.await_ready(child, "http://127.0.0.1:4173", pid_file, log)
                        else:
                            with self.assertRaises(ValueError):
                                module.await_ready(child, "http://127.0.0.1:4173", pid_file, log)
                    self.assertEqual(pid_file.exists(), scenario in ("timeout", "ready"))


if __name__ == "__main__":
    unittest.main()
