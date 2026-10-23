"""The local driver advances only a complete, sealed wave."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_driver_controller  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverControllerTests(unittest.TestCase):
    """Use the public graph commands with a disposable local worker."""

    def test_authorized_attempt_without_handle_never_starts_again(self) -> None:
        """A crash after authorization leaves an unresolved, single-use attempt."""
        with tempfile.TemporaryDirectory() as directory:
            case = Case("codex", Path(directory))
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            opened = subprocess.run(
                [sys.executable, str(SCRIPTS["codex"]), "begin-driver-wave", str(case.path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(opened.returncode, 0, opened.stderr)
            issued = json.loads(opened.stdout)["dispatches"][0]
            dispatch_id = issued["dispatch_id"]
            record = case.read()["graph"]["dispatches"][dispatch_id]
            prompt = case.path.parent / "driver-evidence" / dispatch_id / "prompt.txt"
            prompt.parent.mkdir(parents=True)
            prompt.write_text(issued["prompt_prefix"] + "\n" + issued["prompt_sections"] + "\n")
            authorized = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS["codex"]),
                    "authorize-driver",
                    str(case.path),
                    "--session",
                    "S",
                    "--dispatch-id",
                    dispatch_id,
                    "--prompt-file",
                    str(prompt),
                    "--role",
                    record["contract"]["role"],
                    "--driver-run-id",
                    "first-run",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(authorized.returncode, 0, authorized.stderr)
            before = case.path.read_bytes()

            def command(_prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                self.fail("an authorized attempt must not launch twice")

            report = graph_driver_controller.drive_once(
                case.path,
                "S",
                SCRIPTS["codex"],
                Path(directory),
                "codex",
                command,
                lambda _path, _code: {"outcome": "done", "evidence": "impossible"},
            )
            self.assertEqual(report["status"], "unresolved")
            self.assertEqual(case.path.read_bytes(), before)

    def test_records_a_complete_wave_after_real_process_exit(self) -> None:
        """The controller issues, authorizes, launches, seals and records one wave."""
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
            for provider in ("claude", "codex"):
                case = Case(provider, base)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                if provider == "codex":
                    case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))

                def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                    return [sys.executable, "-c", "import sys; print(sys.stdin.readline().strip())"], None, prompt

                def result(output: Path, _code: int, current: str = provider) -> dict[str, Any]:
                    self.assertTrue(output.read_text().startswith("CODERAILS_GRAPH_DISPATCH="))
                    parsed = {"outcome": "done", "evidence": "disposable worker"}
                    if current == "codex":
                        (output.parent / "final.json").write_text(json.dumps(parsed))
                    return parsed

                deadline = 20
                report: dict[str, Any] = {"status": "unresolved"}
                while deadline:
                    report = graph_driver_controller.drive_once(
                        case.path, "S", SCRIPTS[provider], checkout, provider, command, result
                    )
                    if report["status"] == "recorded":
                        break
                    self.assertEqual(report["status"], "running")
                    deadline -= 1
                self.assertEqual(report["status"], "recorded", (provider, report))
                state = case.read()
                self.assertIsNone(state["graph"]["active_wave"])
                self.assertTrue(any(node["status"] == "done" for node in state["graph"]["nodes"].values()))


if __name__ == "__main__":
    unittest.main()
