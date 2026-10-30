"""Claude controller input must be the exact snapshot checked against real authorization."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
import graph_driver_controller  # noqa: E402
import graph_driver_process  # noqa: E402

from hooks.scripts.lib import graph_driver_claude  # noqa: E402
from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests import test_driver_controller as controller_tests  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class ClaudePromptTests(unittest.TestCase):
    """Use public graph authorization and the real durable process wrapper with an inert child."""

    def prepare(self, base: Path) -> tuple[Case, Path]:
        """Create one scoped driver wave and a retained checkout."""
        case = Case("claude", base)
        controller_tests.DriverControllerTests.scoped(case)
        state = case.read()
        state["work_units"]["1"]["scope"] += " café Ω\nsecond line\n"
        case.write(state)
        self.assertEqual(case.graph("convert").returncode, 0)
        self.assertEqual(case.graph("cutover-driver").returncode, 0)
        case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
        checkout = base / "checkout"
        controller_tests.DriverControllerTests.checkout(checkout)
        return case, checkout

    def finish(self, case: Case, release: Path) -> None:
        """Release only the inert children this test started and reap their wrappers."""
        release.touch()
        for launch in (case.path.parent / "driver-evidence").glob("*/launch.json"):
            self.assertEqual(graph_driver_process.observe(launch.parent, 5)["status"], "finished")

    def test_controller_snapshot_survives_replacement_and_removal(self) -> None:
        """After actual authorization, neither source change may replace the bytes the process receives."""
        for remove in (False, True):
            with self.subTest(remove=remove):
                self._assert_snapshot_survives(remove)

    def _assert_snapshot_survives(self, remove: bool) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, checkout = self.prepare(base)
            capture, release = base / "captured.bin", base / "release"
            expected: list[bytes] = []
            load = graph_driver_controller._load  # pyright: ignore[reportPrivateUsage]

            def mutate(path: Path, session: str) -> dict[str, Any]:
                state = load(path, session)
                for identifier, record in state["graph"]["dispatches"].items():
                    if record.get("authorized") is not None:
                        prompt = path.parent / "driver-evidence" / identifier / "prompt.txt"
                        expected.append(prompt.read_bytes())
                        if remove:
                            prompt.unlink()
                        else:
                            prompt.write_bytes(b"replacement must not reach worker\n")
                return state

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                _, environment, source = graph_driver_claude.command(prompt, checkout)
                code = (
                    "import sys,time\nfrom pathlib import Path\n"
                    f"Path({str(capture)!r}).write_bytes(sys.stdin.buffer.read())\n"
                    f"while not Path({str(release)!r}).exists(): time.sleep(0.01)\n"
                )
                return [sys.executable, "-c", code], environment, source

            try:
                with patch.object(graph_driver_controller, "_load", side_effect=mutate):
                    try:
                        report = graph_driver_controller.drive_once(
                            case.path,
                            "S",
                            SCRIPTS["claude"],
                            checkout,
                            "claude",
                            command,
                            lambda _path, _code: {"outcome": "failed", "evidence": "inert source probe"},
                        )
                    except ValueError as error:
                        self.fail(f"authorized snapshot could not reach the process: {error}")
                self.assertEqual(report["status"], "running")
                deadline = time.monotonic() + 5
                while not capture.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(len(expected), 1)
                self.assertEqual(capture.read_bytes(), expected[0])
                self.assertIn("café Ω".encode(), expected[0])
                self.assertTrue(expected[0].endswith(b"\n"))
            finally:
                self.finish(case, release)

    def test_real_authorized_digest_mismatch_refuses_before_process_start(self) -> None:
        """Changing the file between capture and public authorization cannot change authorized input silently."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case, checkout = self.prepare(base)
            release = base / "release"
            changed: list[Path] = []

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                _, environment, source = graph_driver_claude.command(prompt, checkout)
                prompt.write_bytes(prompt.read_bytes() + b"\nchanged before authorization\n")
                changed.append(prompt)
                code = (
                    f"import time\nfrom pathlib import Path\nwhile not Path({str(release)!r}).exists(): time.sleep(.01)"
                )
                return [sys.executable, "-c", code], environment, source

            try:
                with self.assertRaisesRegex(ValueError, "prompt changed after authorization"):
                    graph_driver_controller.drive_once(
                        case.path,
                        "S",
                        SCRIPTS["claude"],
                        checkout,
                        "claude",
                        command,
                        lambda _path, _code: {"outcome": "failed", "evidence": "inert source probe"},
                    )
                self.assertEqual(len(changed), 1)
                state = case.read()
                authorized = next(iter(state["graph"]["dispatches"].values()))["authorized"]
                self.assertEqual(authorized["prompt_sha256"], hashlib.sha256(changed[0].read_bytes()).hexdigest())
                self.assertFalse(list((case.path.parent / "driver-evidence").glob("*/launch.json")))
            finally:
                self.finish(case, release)


if __name__ == "__main__":
    unittest.main()
