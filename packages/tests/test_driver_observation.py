"""The graph driver reports a worker that has no terminal record."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))

import graph_driver_controller  # noqa: E402
import graph_driver_process  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverObservationTests(unittest.TestCase):
    """Check the reason returned by the supported drive command."""

    def test_drive_reports_missing_terminal_without_retrying_worker(self) -> None:
        """The operator sees why a started worker is unresolved."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = Case("codex", base)
            state = case.read()
            state["work_units"]["1"] = {"status": "pending", "scope": "Build the disposable unit"}
            case.write(state)
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            checkout = base / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=t@example.test",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "first",
                ],
                check=True,
            )

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "pass"], None, prompt

            observation = {"status": "unresolved", "reason": "worker_identity_unconfirmed_terminal_missing"}
            with (
                patch.object(graph_driver_process, "start", return_value={"status": "started"}),
                patch.object(graph_driver_process, "observe", return_value=observation),
            ):
                report = graph_driver_controller.drive_once(
                    case.path, "S", SCRIPTS["codex"], checkout, "codex", command, lambda _path, _code: {}
                )
            self.assertEqual(
                {key: report[key] for key in ("status", "reason", "node")},
                {"status": "unresolved", "reason": "worker_identity_unconfirmed_terminal_missing", "node": "U3[1]"},
            )
            self.assertEqual(Path(report["attempt"]).parent.name, "driver-evidence")

    def test_foreground_wait_returns_running_without_duplicate_launch(self) -> None:
        """A slow child keeps its attempt when the foreground wait ends."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=t@example.test",
                    "commit",
                    "-q",
                    "--allow-empty",
                    "-m",
                    "first",
                ],
                check=True,
            )
            case = Case("codex", base)
            state = case.read()
            state["work_units"]["1"] = {"status": "pending", "scope": "Build the disposable unit"}
            case.write(state)
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "import time; time.sleep(2); print('done')"], None, prompt

            def parsed(_path: Path, _code: int) -> dict[str, str]:
                return {"outcome": "failed", "evidence": "disposable failure"}

            first = graph_driver_controller.drive_wave(
                case.path, "S", SCRIPTS["codex"], checkout, "codex", command, parsed, wait_seconds=0
            )
            self.assertEqual((first["status"], first["reason"]), ("running", "wait_limit"))
            attempt = Path(first["attempt"])
            launch = (attempt / "launch.json").read_bytes()
            second = graph_driver_controller.drive_wave(
                case.path, "S", SCRIPTS["codex"], checkout, "codex", command, parsed, wait_seconds=0
            )
            self.assertEqual(second["status"], "running")
            self.assertEqual((attempt / "launch.json").read_bytes(), launch)
            self.assertTrue((attempt / "stderr.log").exists())
            finished = graph_driver_controller.drive_wave(
                case.path, "S", SCRIPTS["codex"], checkout, "codex", command, parsed, wait_seconds=5
            )
            self.assertEqual(finished["status"], "recorded")


if __name__ == "__main__":
    unittest.main()
