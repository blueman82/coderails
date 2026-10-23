"""Both provider graph commands record only sealed driver worker attempts."""

from __future__ import annotations

import hashlib
import json
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
import graph_driver_evidence  # noqa: E402

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case  # noqa: E402
from packages.tests.test_driver_authorize import frozen_evals  # noqa: E402


class DriverWaveTests(unittest.TestCase):
    """Exercise the real Claude and Codex graph CLIs on disposable files."""

    def test_public_begin_reserves_root_control_without_worker_dispatch(self) -> None:
        """A direct CLI call owns the proof wave without issuing a worker."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                state = case.read()
                state["graph"]["nodes"]["S13-proof"] = state["graph"]["nodes"].pop("U3[1]")
                state["graph"]["nodes"]["S13-proof"]["label"] = "Run frozen proofs"
                case.write(state)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
                opened = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "begin-driver-wave", str(case.path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(opened.returncode, 0, (provider, opened.stderr))
                self.assertEqual(json.loads(opened.stdout)["dispatches"], [])
                self.assertEqual(case.read()["graph"]["active_wave"]["nodes"], ["S13-proof"])

    def test_record_driver_wave_requires_seal_and_final_report(self) -> None:
        """A sealed done result still needs the existing final-report gate."""
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
                state: dict[str, Any] = case.read()
                state["revision"] += 1
                wave_id = f"wave-{state['revision']}"
                node_id = "U3[1]"
                dispatch_id = "disp_test_" + provider
                state["graph"]["active_wave"] = {"wave_id": wave_id, "revision": state["revision"], "nodes": [node_id]}
                state["graph"]["nodes"][node_id].update(status="running", outcome="running")
                state["graph"]["dispatches"][dispatch_id] = {
                    "node_id": node_id,
                    "wave_id": wave_id,
                    "revision": state["revision"],
                    "attempt": 1,
                    "task_name": "test-worker",
                    "dispatch_mode": "driver",
                    "final_report_required": True,
                    "authorized": {
                        "driver_run_id": "test-run",
                        "prompt_sha256": hashlib.sha256(b"CODERAILS_GRAPH_DISPATCH=test\n").hexdigest(),
                    },
                }
                case.write(state)
                result = {"outcome": "done", "evidence": "worker result"}
                artifact = case.path.parent / "driver-evidence" / dispatch_id
                artifact.mkdir(parents=True)
                (artifact / "prompt.txt").write_text("CODERAILS_GRAPH_DISPATCH=test\n")
                (artifact / "output.jsonl").write_text('{"type":"turn.completed"}\n')
                if provider == "codex":
                    (artifact / "final.json").write_text(json.dumps(result))
                head = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
                with patch.object(graph_driver_evidence, "publication", return_value={"number": 42, "head": head}):
                    ref = graph_driver_evidence.seal(
                        case.path, state, node_id, dispatch_id, checkout, provider, 0, result
                    )
                report = {"wave_id": wave_id, "results": {node_id: result}, "references": {node_id: ref}}
                missing = json.dumps({**report, "references": {}})
                before = case.path.read_bytes()
                denied = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "record-driver-wave", str(case.path), missing],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(denied.returncode, 0)
                self.assertEqual(case.path.read_bytes(), before)
                backup = case.path.with_name("progress.json.pre-driver")
                original_backup = backup.read_bytes()
                backup.write_bytes(original_backup + b" ")
                corrupted = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "record-driver-wave", str(case.path), json.dumps(report)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(corrupted.returncode, 0, (provider, corrupted.stderr))
                self.assertEqual(case.path.read_bytes(), before)
                backup.write_bytes(original_backup)
                unreviewed = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "record-driver-wave", str(case.path), json.dumps(report)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(unreviewed.returncode, 0, (provider, unreviewed.stderr))
                self.assertIn("final_report_invalid", unreviewed.stderr)
                self.assertEqual(case.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
