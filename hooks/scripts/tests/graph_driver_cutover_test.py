#!/usr/bin/env python3
"""A driver cutover is an explicit one-way graph operation on both providers."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case


class DriverCutoverTests(unittest.TestCase):
    """Exercise both public provider commands against disposable state files."""

    def test_quiescent_graph_cuts_over_once_on_both_providers(self) -> None:
        """A valid graph crosses the boundary once and keeps its exact old bytes."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                before = case.read()
                original_bytes = case.path.read_bytes()
                result = case.graph("cutover-driver")
                self.assertEqual(result.returncode, 0, (provider, result.stderr))
                report = json.loads(result.stdout)
                after = case.read()
                self.assertEqual(report["driver_from_revision"], after["revision"] + 1)
                self.assertEqual(after["graph"]["dispatch_mode"], "driver")
                self.assertEqual(after["graph"]["native_last_revision"], before["revision"])
                self.assertEqual(after["graph"]["native_backup_sha256"], hashlib.sha256(original_bytes).hexdigest())
                backup = case.path.with_name("progress.json.pre-driver")
                self.assertEqual(backup.read_bytes(), original_bytes)
                once = case.path.read_bytes()
                again = case.graph("cutover-driver")
                self.assertNotEqual(again.returncode, 0)
                self.assertEqual(case.path.read_bytes(), once)

    def test_existing_cutover_backup_refuses_without_overwrite(self) -> None:
        """A prior backup cannot be replaced by another cutover."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                backup = case.path.with_name("progress.json.pre-driver")
                backup.write_bytes(b"earlier evidence")
                before = case.path.read_bytes()
                result = case.graph("cutover-driver")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(case.path.read_bytes(), before)
                self.assertEqual(backup.read_bytes(), b"earlier evidence")

    def test_active_wave_refuses_cutover_without_mutation(self) -> None:
        """A running worker must finish before the mode changes."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                active = case.read()
                active["revision"] += 1
                wave_id = f"wave-{active['revision']}"
                active["graph"]["active_wave"] = {
                    "wave_id": wave_id,
                    "revision": active["revision"],
                    "nodes": ["U3[1]"],
                }
                active["graph"]["nodes"]["U3[1]"].update(status="running", outcome="running")
                case.write(active)
                before = case.path.read_bytes()
                result = case.graph("cutover-driver")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("active wave", result.stderr)
                self.assertEqual(case.path.read_bytes(), before)

    def test_native_wave_command_refuses_driver_graph(self) -> None:
        """The old wave command cannot start work after cutover."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                before = case.path.read_bytes()
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "begin-wave", str(case.path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("driver", result.stderr.lower())
                self.assertEqual(case.path.read_bytes(), before)

    def test_native_authorization_refuses_driver_graph(self) -> None:
        """The old authorization command cannot admit a worker after cutover."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                before = case.path.read_bytes()
                if provider == "claude":
                    flags = ["--session", "S", "--prompt", "bad", "--subagent-type", "coderails:loop-worker"]
                else:
                    prompt = case.path.with_name("bad-prompt.txt")
                    prompt.write_text("bad")
                    flags = [
                        "--session",
                        "S",
                        "--dispatch-id",
                        "missing",
                        "--task-name",
                        "missing",
                        "--message-file",
                        str(prompt),
                    ]
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "authorize-dispatch", str(case.path), *flags],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("driver", result.stderr.lower())
                self.assertEqual(case.path.read_bytes(), before)

    def test_native_record_wave_refuses_driver_graph(self) -> None:
        """The old recorder cannot accept an unbound result after cutover."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                state = case.read()
                state["revision"] += 1
                wave_id = f"wave-{state['revision']}"
                state["graph"]["active_wave"] = {"wave_id": wave_id, "revision": state["revision"], "nodes": ["U3[1]"]}
                state["graph"]["nodes"]["U3[1]"].update(status="running", outcome="running")
                case.write(state)
                before = case.path.read_bytes()
                report = json.dumps(
                    {"wave_id": wave_id, "results": {"U3[1]": {"outcome": "done", "evidence": "forged"}}}
                )
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "record-wave", str(case.path), report],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("driver", result.stderr.lower())
                self.assertEqual(case.path.read_bytes(), before)

    def test_driver_begin_issues_the_full_ready_wave(self) -> None:
        """The driver starts every ready node and issues one owned record per node."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                self.assertEqual(case.graph("cutover-driver").returncode, 0)
                if provider == "codex":
                    evals = {
                        "scope": "loop",
                        "task_ref": "L",
                        "session_id": "S",
                        "loop_id": "L",
                        "verification_level": 1,
                        "verification_justification": "test suite",
                        "frozen_sha": "fixture",
                        "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
                        "result": None,
                        "grading": None,
                    }
                    case.path.with_name("evals.json").write_text(json.dumps(evals))
                result = subprocess.run(
                    [sys.executable, str(SCRIPTS[provider]), "begin-driver-wave", str(case.path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, (provider, result.stderr))
                state = case.read()
                active = state["graph"]["active_wave"]
                self.assertTrue(active["nodes"])
                records = [r for r in state["graph"]["dispatches"].values() if r["wave_id"] == active["wave_id"]]
                self.assertEqual({r["node_id"] for r in records}, set(active["nodes"]))
                self.assertTrue(all(r["dispatch_mode"] == "driver" and r["authorized"] is None for r in records))

    def test_unmarked_cutover_fields_refuse_without_mutation(self) -> None:
        """A partial mode marker is invalid evidence."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                state = case.read()
                state["graph"]["native_last_revision"] = state["revision"]
                case.write(state)
                before = case.path.read_bytes()
                result = case.graph("cutover-driver")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("cutover", result.stderr.lower())
                self.assertEqual(case.path.read_bytes(), before)

    def test_forged_native_history_cannot_cross_cutover(self) -> None:
        """A forged old worker reference cannot be retained at cutover."""
        with tempfile.TemporaryDirectory() as directory:
            for provider in ("claude", "codex"):
                case = Case(provider, Path(directory))
                self.assertEqual(case.graph("convert").returncode, 0)
                state = case.read()
                state["graph"]["nodes"]["U3[1]"]["evidence"].append({"kind": "forged_worker"})
                case.write(state)
                before = case.path.read_bytes()
                result = case.graph("cutover-driver")
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(case.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
