"""The local driver advances only a complete, sealed wave."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
import graph_driver_controller  # noqa: E402
import graph_driver_process  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests import test_driver_controller as controller_tests  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverPromptTests(unittest.TestCase):
    """Bind a single immutable snapshot to the recorded authorization."""

    scoped = staticmethod(controller_tests.DriverControllerTests.scoped)
    checkout = staticmethod(controller_tests.DriverControllerTests.checkout)

    def test_digest_mismatch_stops_before_launch(self) -> None:
        """A checked prompt cannot change between graph authorization and process launch."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = Case("codex", base)
            self.scoped(case)
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            checkout = base / "checkout"
            self.checkout(checkout)
            load = graph_driver_controller._load  # pyright: ignore[reportPrivateUsage]

            def change_after_authorize(path: Path, session: str) -> dict[str, Any]:
                state = load(path, session)
                for record in state["graph"].get("dispatches", {}).values():
                    if record.get("authorized") is not None:
                        record["authorized"]["prompt_sha256"] = "0" * 64
                return state

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "print('must not run')"], None, prompt

            with (
                patch.object(graph_driver_controller, "_load", side_effect=change_after_authorize),
                patch.object(graph_driver_process, "start", side_effect=AssertionError("launched")),
                self.assertRaisesRegex(ValueError, "prompt changed after authorization"),
            ):
                graph_driver_controller.drive_once(
                    case.path,
                    "S",
                    SCRIPTS["codex"],
                    checkout,
                    "codex",
                    command,
                    lambda _path, _code: {"outcome": "done", "evidence": "impossible"},
                )
            self.assertFalse(list((base / "driver-evidence").rglob("launch.json")))

    def test_snapshot_survives_source_removal_after_authorization(self) -> None:
        """A file removed after authorization cannot change forwarded prompt bytes."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = Case("codex", base)
            self.scoped(case)
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            checkout = base / "checkout"
            self.checkout(checkout)
            load = graph_driver_controller._load  # pyright: ignore[reportPrivateUsage]
            captured: list[bytes] = []

            def remove_after_authorize(path: Path, session: str) -> dict[str, Any]:
                state = load(path, session)
                for identifier, record in state["graph"].get("dispatches", {}).items():
                    if record.get("authorized") is not None:
                        prompt = path.parent / "driver-evidence" / identifier / "prompt.txt"
                        captured.append(prompt.read_bytes())
                        prompt.unlink()
                return state

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "print('synthetic source-only child')"], None, prompt

            with (
                patch.object(graph_driver_controller, "_load", side_effect=remove_after_authorize),
                patch.object(graph_driver_process, "start") as launch,
                patch.object(graph_driver_process, "observe", return_value={"status": "running"}),
            ):
                report = graph_driver_controller.drive_once(
                    case.path,
                    "S",
                    SCRIPTS["codex"],
                    checkout,
                    "codex",
                    command,
                    lambda _path, _code: {"outcome": "done", "evidence": "synthetic source-only"},
                )
            self.assertEqual(report["status"], "running")
            self.assertEqual(len(captured), 1)
            self.assertEqual(launch.call_args.kwargs["stdin_bytes"], captured[0])


if __name__ == "__main__":
    unittest.main()
