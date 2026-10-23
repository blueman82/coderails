"""The local driver advances only a complete, sealed wave."""

from __future__ import annotations

import copy
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
import graph_driver_control  # noqa: E402
import graph_driver_controller  # noqa: E402
import graph_driver_evidence  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverControllerTests(unittest.TestCase):
    """Use the public graph commands with a disposable local worker."""

    def setUp(self) -> None:
        """Give fake worker runs a matching disposable PR."""

        def published(checkout: Path, *, require_merged: bool = False) -> dict[str, object]:
            head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            return {"number": 42, "head": head}

        publisher = patch.object(
            graph_driver_evidence,
            "publication",
            side_effect=published,
        )
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

    def test_unpublished_source_pauses_before_seal(self) -> None:
        """A completed worker cannot become graph evidence before publication."""
        with patch.object(graph_driver_evidence, "publication", side_effect=ValueError("no open PR")):
            report = graph_driver_controller._publication_pause(  # pyright: ignore[reportPrivateUsage]
                Path("/unused"), "U3[1]", {"outcome": "done"}
            )
        self.assertEqual((report or {}).get("reason"), "publication_required")

    @staticmethod
    def scoped(case: Case) -> None:
        """Give the disposable worker a real, narrow assignment."""
        state = case.read()
        state["work_units"]["1"] = {"status": "pending", "scope": "Build the disposable unit"}
        case.write(state)

    @staticmethod
    def checkout(path: Path) -> None:
        """Create a retained checkout with a real HEAD for worker evidence."""
        path.mkdir()
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
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

    def test_missing_implementation_task_pauses_before_wave(self) -> None:
        """An empty graph unit cannot authorize a worker's unscoped done claim."""
        with tempfile.TemporaryDirectory() as directory:
            case = Case("codex", Path(directory))
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            before = case.path.read_bytes()

            def command(_prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                self.fail("a missing task must not launch a worker")

            report = graph_driver_controller.drive_once(
                case.path,
                "S",
                SCRIPTS["codex"],
                Path(directory),
                "codex",
                command,
                lambda _path, _code: {"outcome": "done", "evidence": "impossible"},
            )
            self.assertEqual(report, {"status": "paused", "reason": "missing_task", "nodes": ["U3[1]"]})
            self.assertEqual(case.path.read_bytes(), before)

    def test_two_workers_need_distinct_checkouts_before_wave(self) -> None:
        """One mutable checkout cannot preserve both workers' HEAD evidence."""
        with tempfile.TemporaryDirectory() as directory:
            case = Case("codex", Path(directory))
            self.scoped(case)
            self.assertEqual(case.graph("convert").returncode, 0)
            added = case.graph("add-unit", "--loop-id", "L", "--unit", "2", "--scope", "Build second unit")
            self.assertEqual(added.returncode, 0, added.stderr)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            before = case.path.read_bytes()

            def command(_prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                self.fail("a shared checkout must not start either worker")

            report = graph_driver_controller.drive_once(
                case.path,
                "S",
                SCRIPTS["codex"],
                Path(directory),
                "codex",
                command,
                lambda _path, _code: {"outcome": "done", "evidence": "impossible"},
            )
            self.assertEqual(report["reason"], "checkout_map_required")
            self.assertEqual(case.path.read_bytes(), before)
            checkouts: dict[str, Path] = {}
            for node_id in ("U3[1]", "U3[2]"):
                worker = Path(directory) / node_id.replace("[", "-").replace("]", "")
                self.checkout(worker)
                checkouts[node_id] = worker
            mapping = Path(directory) / "checkout-map.json"
            mapping.write_text(json.dumps({node_id: str(worker) for node_id, worker in checkouts.items()}))
            checkouts = graph_driver_controller.parse_checkout_map(mapping)

            def run_worker(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "import sys; print(sys.stdin.readline().strip())"], None, prompt

            def result(output: Path, _code: int) -> dict[str, Any]:
                self.assertTrue(output.read_text().startswith("CODERAILS_GRAPH_DISPATCH="))
                parsed = {
                    "outcome": "done",
                    "evidence": "disposable worker",
                    "final_report": {
                        "claims": [{"text": "Disposable result", "label": "verified", "source": "scratch checkout"}],
                        "did_not_verify": [],
                    },
                }
                (output.parent / "final.json").write_text(json.dumps(parsed))
                return parsed

            for _attempt in range(20):
                report = graph_driver_controller.drive_once(
                    case.path, "S", SCRIPTS["codex"], checkouts, "codex", run_worker, result
                )
                if report["status"] == "recorded":
                    break
                self.assertEqual(report["status"], "running")
            self.assertEqual(report["status"], "recorded")
            self.assertEqual(report["nodes"], ["U3[1]", "U3[2]"])
            state = case.read()
            for node_id in checkouts:
                ref = state["graph"]["nodes"][node_id]["evidence"][-1]
                manifest = case.path.parent / "driver-evidence" / ref["dispatch_id"] / "manifest.json"
                self.assertEqual(json.loads(manifest.read_text())["checkout"], str(checkouts[node_id].resolve()))
            self.assertEqual(
                graph_driver_controller._checkout_problem(  # pyright: ignore[reportPrivateUsage]
                    state, ["U3[1]"], checkouts["U3[1]"], case.path
                ),
                "checkout_already_used",
            )

    def test_mixed_root_and_worker_wave_joins_both_results(self) -> None:
        """A root result and a worker result complete the same full-ready-set wave."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            case = Case("codex", base)
            self.scoped(case)
            state = case.read()
            proof = copy.deepcopy(state["graph"]["nodes"]["U3[1]"])
            proof["label"] = "Run frozen proofs"
            state["graph"]["nodes"]["S13-proof"] = proof
            case.write(state)
            self.assertEqual(case.graph("convert").returncode, 0)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
            checkout = base / "checkout"
            self.checkout(checkout)

            def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                return [sys.executable, "-c", "import sys; print(sys.stdin.readline().strip())"], None, prompt

            def result(output: Path, _code: int) -> dict[str, Any]:
                parsed = {
                    "outcome": "done",
                    "evidence": "disposable worker",
                    "final_report": {
                        "claims": [{"text": "Disposable result", "label": "verified", "source": "scratch checkout"}],
                        "did_not_verify": [],
                    },
                }
                (output.parent / "final.json").write_text(json.dumps(parsed))
                return parsed

            first = graph_driver_controller.drive_once(
                case.path, "S", SCRIPTS["codex"], checkout, "codex", command, result
            )
            self.assertEqual(first, {"status": "paused", "reason": "control_node", "nodes": ["S13-proof"]})
            result_file = base / "root-result.json"
            result_file.write_text(json.dumps({"outcome": "done", "evidence": "disposable root proof"}))
            graph_driver_control.stage(case.path, case.read(), "S", "S13-proof", result_file)
            report: dict[str, Any] = {"status": "unresolved"}
            for _attempt in range(20):
                report = graph_driver_controller.drive_once(
                    case.path, "S", SCRIPTS["codex"], checkout, "codex", command, result
                )
                if report["status"] == "recorded":
                    break
                self.assertEqual(report["status"], "running")
            self.assertEqual(report["nodes"], ["S13-proof", "U3[1]"])
            state = case.read()
            self.assertEqual(state["graph"]["nodes"]["S13-proof"]["evidence"][-1]["kind"], "root_control")
            self.assertEqual(state["graph"]["nodes"]["U3[1]"]["evidence"][-1]["kind"], "driver_worker")
            reference = state["graph"]["nodes"]["S13-proof"]["evidence"][-1]
            later = copy.deepcopy(state)
            later["graph"]["active_wave"] = {"wave_id": "wave-999", "revision": 999, "nodes": ["S13-retro"]}
            graph_driver_control.validate(case.path, later, "S13-proof", reference)
            later["graph"]["nodes"]["S13-proof"]["evidence"] = []
            with self.assertRaisesRegex(ValueError, "another wave"):
                graph_driver_control.validate(case.path, later, "S13-proof", reference)

    def test_root_owned_proof_node_pauses_before_dispatch(self) -> None:
        """A proof step cannot be satisfied by an external model's done message."""
        with tempfile.TemporaryDirectory() as directory:
            case = Case("codex", Path(directory))
            state = case.read()
            state["graph"]["nodes"]["S13-proof"] = state["graph"]["nodes"].pop("U3[1]")
            state["graph"]["nodes"]["S13-proof"]["label"] = "Run frozen proofs"
            case.write(state)
            converted = case.graph("convert")
            self.assertEqual(converted.returncode, 0, converted.stderr)
            self.assertEqual(case.graph("cutover-driver").returncode, 0)
            case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))

            def command(_prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                self.fail("a root-owned proof must not launch a worker")

            report = graph_driver_controller.drive_once(
                case.path,
                "S",
                SCRIPTS["codex"],
                Path(directory),
                "codex",
                command,
                lambda _path, _code: {"outcome": "done", "evidence": "impossible"},
            )
            self.assertEqual(report, {"status": "paused", "reason": "control_node", "nodes": ["S13-proof"]})
            self.assertEqual(case.read()["graph"]["active_wave"]["nodes"], ["S13-proof"])
            self.assertFalse(case.read()["graph"]["dispatches"])

    def test_authorized_attempt_without_launch_resumes_setup(self) -> None:
        """A crash before the launch reservation can safely retry setup."""
        with tempfile.TemporaryDirectory() as directory:
            case = Case("codex", Path(directory))
            checkout = Path(directory) / "checkout"
            self.checkout(checkout)
            self.scoped(case)
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
            with self.assertRaisesRegex(ValueError, "role instructions"):
                graph_driver_controller._prompt(  # pyright: ignore[reportPrivateUsage]
                    case.path, case.read(), dispatch_id, record, Path(directory).resolve(), "codex", case.path
                )
            prompt = graph_driver_controller._prompt(  # pyright: ignore[reportPrivateUsage]
                case.path, case.read(), dispatch_id, record, checkout.resolve(), "codex", SCRIPTS["codex"]
            )
            self.assertIn("Role instructions for loop-worker", prompt.read_text())
            self.assertIn("Acceptance: source edits and checks ready for root publication", prompt.read_text())
            authorized = case.graph(
                "authorize-driver",
                "--dispatch-id",
                dispatch_id,
                "--prompt-file",
                str(prompt),
                "--role",
                record["contract"]["role"],
                "--driver-run-id",
                "first-run",
            )
            self.assertEqual(authorized.returncode, 0, authorized.stderr)
            before = case.path.read_bytes()

            def command(_prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                raise ValueError("setup was retried")

            with self.assertRaisesRegex(ValueError, "setup was retried"):
                graph_driver_controller.drive_once(
                    case.path,
                    "S",
                    SCRIPTS["codex"],
                    checkout,
                    "codex",
                    command,
                    lambda _path, _code: {"outcome": "done", "evidence": "impossible"},
                )
            self.assertEqual(case.path.read_bytes(), before)
            resumed = graph_driver_controller.drive_wave(
                case.path,
                "S",
                SCRIPTS["codex"],
                checkout,
                "codex",
                lambda prompt, _record: ([sys.executable, "-c", "print('worker')"], None, prompt),
                lambda _path, _code: {"outcome": "failed", "evidence": "disposable failure"},
            )
            self.assertEqual(resumed["status"], "recorded")
            self.assertTrue((case.path.parent / "driver-evidence" / dispatch_id / "launch.json").exists())

    def test_records_a_complete_wave_after_real_process_exit(self) -> None:
        """The controller issues, authorizes, launches, seals and records one wave."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            self.checkout(checkout)
            for provider in ("claude", "codex"):
                case = Case(provider, base)
                self.scoped(case)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))

                def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
                    self.assertIn("Role instructions for loop-worker", prompt.read_text())
                    self.assertIn("Acceptance: source edits and checks ready for root publication", prompt.read_text())
                    return [sys.executable, "-c", "import sys; print(sys.stdin.readline().strip())"], None, prompt

                def result(output: Path, _code: int, current: str = provider) -> dict[str, Any]:
                    self.assertTrue(output.read_text().startswith("CODERAILS_GRAPH_DISPATCH="))
                    parsed = {
                        "outcome": "done",
                        "evidence": "disposable worker",
                        "final_report": {
                            "claims": [
                                {"text": "Disposable result", "label": "verified", "source": "scratch checkout"}
                            ],
                            "did_not_verify": [],
                        },
                    }
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
