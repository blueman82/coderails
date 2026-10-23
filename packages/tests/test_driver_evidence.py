"""Driver evidence remains bound to raw output and the worker checkout."""

from __future__ import annotations

import hashlib
import json
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

    def commit_empty(self, checkout: Path, message: str) -> None:
        """Advance the disposable worker checkout by one commit."""
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
                message,
            ],
            check=True,
        )

    def check_history(self, state_path: Path, state: dict[str, Any], ref: dict[str, Any]) -> None:
        """Check that each finished driver dispatch has one durable reference."""
        state["graph"]["nodes"] = {"U3[1]": {"evidence": ["native note", ref]}}
        state["graph"]["active_wave"] = None
        self.assertTrue(hasattr(graph_driver_evidence, "validate_history"), "driver history validator is missing")
        graph_driver_evidence.validate_history(state_path, state)
        foreign = deepcopy(state)
        foreign["graph"]["nodes"]["U3[1]"]["evidence"].append(ref)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            graph_driver_evidence.validate_history(state_path, foreign)
        foreign = deepcopy(state)
        foreign["graph"]["nodes"]["U3[1]"]["evidence"] = ["native note"]
        with self.assertRaisesRegex(ValueError, "missing"):
            graph_driver_evidence.validate_history(state_path, foreign)

    def check_backup(self, state_path: Path, state: dict[str, Any]) -> None:
        """A changed backup or native evidence prefix invalidates the cutover."""
        backup = state_path.with_name("progress.json.pre-driver")
        old = {
            "session_id": "S",
            "loop_id": "L",
            "revision": 1,
            "graph": {"nodes": {"U3[1]": {"evidence": ["native note"]}}, "dispatches": {}},
        }
        raw = json.dumps(old).encode()
        backup.write_bytes(raw)
        state["graph"]["native_backup_sha256"] = hashlib.sha256(raw).hexdigest()
        self.assertTrue(hasattr(graph_driver_evidence, "validate_backup"), "native backup validator is missing")
        graph_driver_evidence.validate_backup(state_path, state)
        backup.write_bytes(raw + b" ")
        with self.assertRaisesRegex(ValueError, "backup"):
            graph_driver_evidence.validate_backup(state_path, state)
        backup.write_bytes(raw)
        foreign = deepcopy(state)
        foreign["graph"]["nodes"]["U3[1]"]["evidence"][0] = "changed note"
        with self.assertRaisesRegex(ValueError, "native"):
            graph_driver_evidence.validate_backup(state_path, foreign)

    def test_changed_output_or_head_invalidates_a_sealed_result(self) -> None:
        """A past pass cannot survive changed worker bytes or changed source."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            checkout.mkdir()
            subprocess.run(["git", "init", "-q", str(checkout)], check=True)
            self.commit_empty(checkout, "first")
            state_path = base / "S" / "progress.json"
            state_path.parent.mkdir()
            dispatch_id = "disp_0123456789abcdef"
            state: dict[str, Any] = {
                "session_id": "S",
                "loop_id": "L",
                "graph": {
                    "dispatch_mode": "driver",
                    "driver_from_revision": 3,
                    "native_last_revision": 1,
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
                    },
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
            self.check_history(state_path, state, ref)
            self.check_backup(state_path, state)
            foreign = deepcopy(state)
            foreign["graph"].pop("dispatch_mode")
            with self.assertRaisesRegex(ValueError, "cutover"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            foreign = deepcopy(state)
            foreign["graph"]["driver_from_revision"] = 4
            with self.assertRaisesRegex(ValueError, "cutover"):
                graph_driver_evidence.validate(state_path, foreign, "U3[1]", ref)
            with self.assertRaisesRegex(ValueError, "reference"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", {**ref, "extra": "accepted?"})
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
            self.commit_empty(checkout, "second")
            with self.assertRaisesRegex(ValueError, "HEAD"):
                graph_driver_evidence.validate(state_path, state, "U3[1]", ref)


if __name__ == "__main__":
    unittest.main()
