"""Driver evidence remains bound to raw output and the worker checkout."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages/graph-semantics"))
import graph_driver_evidence  # noqa: E402


class DriverEvidenceTests(unittest.TestCase):
    """Use real files and a disposable Git repository for SHA revalidation."""

    def test_changed_output_or_head_invalidates_a_sealed_result(self) -> None:
        """A past pass cannot survive changed worker bytes or changed source."""
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
            state_path = base / "S" / "progress.json"
            state_path.parent.mkdir()
            dispatch_id = "disp_0123456789abcdef"
            state: dict[str, Any] = {
                "session_id": "S",
                "loop_id": "L",
                "graph": {
                    "dispatches": {
                        dispatch_id: {
                            "node_id": "U3[1]",
                            "wave_id": "wave-3",
                            "revision": 3,
                            "attempt": 1,
                            "dispatch_mode": "driver",
                            "task_name": "worker_one",
                            "authorized": {"driver_run_id": "run-1"},
                        }
                    }
                },
            }
            artifact = state_path.parent / "driver-evidence" / dispatch_id
            artifact.mkdir(parents=True)
            (artifact / "prompt.txt").write_text("build one unit\n")
            output = artifact / "output.jsonl"
            output.write_text('{"type":"turn.completed"}\n')
            ref = graph_driver_evidence.seal(
                state_path, state, "U3[1]", dispatch_id, checkout, "codex", 0, {"outcome": "done"}
            )
            graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
            output.write_text('{"type":"turn.failed"}\n')
            with self.assertRaisesRegex(ValueError, "output"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", ref)
            output.write_text('{"type":"turn.completed"}\n')
            with self.assertRaisesRegex(ValueError, "already sealed"):
                graph_driver_evidence.seal(
                    state_path, state, "U3[1]", dispatch_id, checkout, "codex", 0, {"outcome": "done"}
                )
            with self.assertRaisesRegex(ValueError, "foreign"):
                graph_driver_evidence.validate(state_path, state, "U3[2]", ref)
            foreign = deepcopy(state)
            foreign["session_id"] = "other-session"
            with self.assertRaisesRegex(ValueError, "foreign"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            foreign = deepcopy(state)
            foreign["graph"]["dispatches"][dispatch_id]["attempt"] = 2
            with self.assertRaisesRegex(ValueError, "attempt"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            foreign = deepcopy(state)
            foreign["graph"]["dispatches"][dispatch_id]["authorized"]["driver_run_id"] = "other-run"
            with self.assertRaisesRegex(ValueError, "foreign"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
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
                    "second",
                ],
                check=True,
            )
            with self.assertRaisesRegex(ValueError, "HEAD"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", ref)


if __name__ == "__main__":
    unittest.main()
