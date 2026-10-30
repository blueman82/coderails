"""A paused worker keeps its raw attempt fixed until root publishes a PR."""

from __future__ import annotations

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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
import graph_driver_controller  # noqa: E402
import graph_driver_evidence  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverPrepublicationTests(unittest.TestCase):
    """Run a real local child while PR publication is absent."""

    def setUp(self) -> None:
        """Give a later published result one disposable PR lookup."""

        def published(checkout: Path, *, require_merged: bool = False) -> dict[str, object]:
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            return {"number": 42, "head": head}

        publisher = patch.object(graph_driver_evidence, "publication", side_effect=published)
        publisher.start()
        self.addCleanup(publisher.stop)
        tool_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tool_dir.cleanup)
        gh = Path(tool_dir.name) / "gh"
        gh.write_text(
            "#!/usr/bin/env python3\nimport json, subprocess\n"
            "head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()\n"
            "print(json.dumps({'number': 42, 'state': 'OPEN', 'headRefOid': head}))\n"
        )
        gh.chmod(0o755)
        environment = patch.dict(os.environ, PATH=f"{tool_dir.name}:{os.environ['PATH']}")
        environment.start()
        self.addCleanup(environment.stop)

    def test_unpublished_worker_seals_raw_attempt_before_pause(self) -> None:
        """A changed attempt cannot be replayed after a publication pause."""
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
                return [sys.executable, "-c", "print('worker finished')"], None, prompt

            def result(output: Path, _code: int) -> dict[str, Any]:
                parsed = {
                    "outcome": "done",
                    "evidence": "disposable worker",
                    "final_report": {
                        "claims": [{"text": "Worker finished", "label": "verified", "source": "scratch"}],
                        "did_not_verify": [],
                    },
                }
                (output.parent / "final.json").write_text(json.dumps(parsed))
                return parsed

            report: dict[str, Any] = {"status": "unresolved"}
            with patch.object(graph_driver_evidence, "publication", side_effect=ValueError("no open PR")):
                for _attempt in range(30):
                    report = graph_driver_controller.drive_once(
                        case.path, "S", SCRIPTS["codex"], checkout, "codex", command, result
                    )
                    if report["status"] == "paused":
                        break
                    self.assertEqual(report["status"], "running")
            self.assertEqual(report["reason"], "publication_required")
            state = case.read()
            self.assertEqual(state["graph"]["nodes"]["U3[1]"]["status"], "running")
            dispatch_id = next(
                key for key, item in state["graph"]["dispatches"].items() if item.get("dispatch_mode") == "driver"
            )
            artifact = case.path.parent / "driver-evidence" / dispatch_id
            self.assertTrue((artifact / "prepublication.json").is_file())
            self.assertFalse((artifact / "manifest.json").exists())
            output = artifact / "output.jsonl"
            original = output.read_bytes()
            output.write_bytes(original + b"tampered\n")
            with (
                patch.object(graph_driver_evidence, "publication", side_effect=ValueError("no open PR")),
                self.assertRaisesRegex(ValueError, "prepublication output changed"),
            ):
                graph_driver_controller.drive_once(case.path, "S", SCRIPTS["codex"], checkout, "codex", command, result)
            output.write_bytes(original)
            done = graph_driver_controller.drive_once(
                case.path, "S", SCRIPTS["codex"], checkout, "codex", command, result
            )
            self.assertEqual(done["status"], "recorded")
            self.assertTrue((artifact / "manifest.json").is_file())
            pending = artifact / "prepublication.json"
            pending.write_bytes(pending.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "prepublication evidence changed"):
                graph_driver_evidence.validate_history(case.path, case.read())


if __name__ == "__main__":
    unittest.main()
