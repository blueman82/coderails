"""A pending unit can receive a bounded, auditable scope note."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case
from packages.tests.test_driver_authorize import frozen_evals


class DriverScopeNoteTests(unittest.TestCase):
    """Exercise both public graph commands against disposable state."""

    def test_append_preserves_history_and_refuses_stale_input(self) -> None:
        """An accepted note changes only the task and revision; stale input changes nothing."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in SCRIPTS:
                case = Case(provider, Path(directory))
                state = case.read()
                state["work_units"]["1"] = {"status": "pending", "scope": "Original task"}
                case.write(state)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                before = case.read()
                flags = [
                    "--loop-id",
                    "L",
                    "--revision",
                    str(before["revision"]),
                    "--unit",
                    "1",
                    "--expected-scope-sha256",
                    hashlib.sha256(b"Original task").hexdigest(),
                    "--note",
                    "Check the source checkpoint.",
                    "--reason",
                    "The pinned plan is absent.",
                ]
                accepted = case.graph("append-unit-scope-note", *flags)
                self.assertEqual(accepted.returncode, 0, (provider, accepted.stderr))
                after = case.read()
                self.assertEqual(after["revision"], before["revision"] + 1)
                self.assertEqual(after["graph"], before["graph"])
                self.assertTrue(after["work_units"]["1"]["scope"].startswith("Original task\n"))
                self.assertIn("Check the source checkpoint.", after["work_units"]["1"]["scope"])
                note = after["work_units"]["1"]["scope_notes"][-1]
                self.assertEqual(note["old_sha256"], hashlib.sha256(b"Original task").hexdigest())
                self.assertEqual(
                    note["new_sha256"], hashlib.sha256(after["work_units"]["1"]["scope"].encode()).hexdigest()
                )
                self.assertEqual(note["reason"], "The pinned plan is absent.")
                saved = case.path.read_bytes()
                stale = case.graph("append-unit-scope-note", *flags)
                self.assertNotEqual(stale.returncode, 0)
                self.assertEqual(case.path.read_bytes(), saved)

    def test_refuses_foreign_changed_active_and_done(self) -> None:
        """Invalid ownership or graph state leaves the state file unchanged."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in SCRIPTS:
                for condition in ("foreign", "loop", "hash", "active", "done"):
                    case = Case(provider, Path(directory) / condition)
                    state = case.read()
                    state["work_units"]["1"] = {"status": "pending", "scope": "Original task"}
                    case.write(state)
                    self.assertEqual(case.graph("convert").returncode, 0)
                    self.assertEqual(case.graph("cutover-driver").returncode, 0)
                    state = case.read()
                    if condition == "active":
                        state["graph"]["active_wave"] = {
                            "wave_id": "open",
                            "nodes": ["U3[1]"],
                            "revision": state["revision"],
                        }
                    elif condition == "done":
                        state["work_units"]["1"]["status"] = "done"
                    case.write(state)
                    flags = [
                        "--loop-id",
                        "foreign" if condition == "loop" else "L",
                        "--revision",
                        str(state["revision"]),
                        "--unit",
                        "1",
                        "--expected-scope-sha256",
                        "0" * 64 if condition == "hash" else hashlib.sha256(b"Original task").hexdigest(),
                        "--note",
                        "Check source.",
                        "--reason",
                        "Pinned plan is absent.",
                    ]
                    before = case.path.read_bytes()
                    result = case.graph(
                        "append-unit-scope-note", *flags, session="foreign" if condition == "foreign" else "S"
                    )
                    self.assertNotEqual(result.returncode, 0, (provider, condition))
                    self.assertEqual(case.path.read_bytes(), before)

    def test_next_wave_prompt_contains_new_note(self) -> None:
        """A new worker prompt and its saved digest include the note."""
        with tempfile.TemporaryDirectory() as directory:
            for provider, script in SCRIPTS.items():
                case = Case(provider, Path(directory))
                state = case.read()
                state["work_units"]["1"] = {"status": "pending", "scope": "Original task"}
                case.write(state)
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
                state = case.read()
                result = case.graph(
                    "append-unit-scope-note",
                    "--loop-id",
                    "L",
                    "--revision",
                    str(state["revision"]),
                    "--unit",
                    "1",
                    "--expected-scope-sha256",
                    hashlib.sha256(b"Original task").hexdigest(),
                    "--note",
                    "Check the source checkpoint.",
                    "--reason",
                    "The pinned plan is absent.",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                wave = subprocess.run(
                    [sys.executable, str(script), "begin-driver-wave", str(case.path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(wave.returncode, 0, (provider, wave.stderr))
                dispatch = json.loads(wave.stdout)["dispatches"][0]
                self.assertIn("Check the source checkpoint.", dispatch["prompt_sections"])
                self.assertEqual(
                    case.read()["graph"]["dispatches"][dispatch["dispatch_id"]]["prompt_sections_sha256"],
                    hashlib.sha256(dispatch["prompt_sections"].encode()).hexdigest(),
                )


if __name__ == "__main__":
    unittest.main()
