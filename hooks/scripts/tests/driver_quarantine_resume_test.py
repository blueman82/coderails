"""Sealed failed evidence remains observable without reopening quarantined workspaces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hooks.scripts.tests.graph_convert_test import Case
from hooks.scripts.tests.lib import claude_transcript_fixture as transcript
from packages.tests import test_driver_controller as controller_fixture
from packages.tests.test_driver_authorize import frozen_evals
from scripts.sandbox import driver_workspace


class QuarantineResumeTests(unittest.TestCase):
    """Use public commands, inert provider processes and disposable owner checkouts."""

    def setUp(self) -> None:
        """Prepare two owned workspaces and an inert structured-result provider."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.case = Case("claude", self.base)
        value = transcript.state(2)
        value.update(session_id="S", loop_id="L")
        value.pop("state_minor")
        for key in ("dispatches", "contract_from_revision"):
            value["graph"].pop(key, None)
        value["work_units"] = {
            str(i): {
                "status": "pending",
                "scope": f"Synthetic unit {i}",
                "manifest": ["allowed.txt"],
                "write_scope": ["allowed.txt"],
            }
            for i in (1, 2)
        }
        self.case.write(value)
        self.assertEqual(self.case.graph("convert").returncode, 0)
        self.assertEqual(self.case.graph("cutover-driver").returncode, 0)
        self.case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
        home, tools = self.base / "home", self.base / "bin"
        tools.mkdir()
        credential = home / ".coderails/worker_credential"
        credential.parent.mkdir(parents=True)
        credential.write_text("CLAUDE_CODE_OAUTH_TOKEN=synthetic-quarantine-token\n")
        credential.chmod(0o600)
        pin = home / ".npm/_npx/fixture/node_modules/@anthropic-ai/sandbox-runtime/package.json"
        pin.parent.mkdir(parents=True)
        pin.write_text('{"version":"0.0.65"}')
        self.release = self.base / "release"
        self.launches = self.base / "launches"
        child = tools / "npx"
        child.write_text(
            f"#!{sys.executable}\nimport json,sys,time\nfrom pathlib import Path\n"
            "prompt=sys.stdin.buffer.read()\n"
            'first=b\'"node_id":"U3[1]"\' in prompt or b\'"node_id": "U3[1]"\' in prompt\n'
            f"with Path({str(self.launches)!r}).open('a') as log: log.write(('first' if first else 'second')+'\\n')\n"
            "deadline=time.monotonic()+10\n"
            f"while not first and not Path({str(self.release)!r}).exists() and time.monotonic()<deadline:\n"
            " time.sleep(.01)\n"
            "print(json.dumps({'type':'system','subtype':'init','session_id':'synthetic'}))\n"
            "print(json.dumps({'type':'result','subtype':'success','is_error':False,'structured_output':"
            "{'outcome':'failed','evidence':'synthetic failed worker','final_report':None}}))\n"
        )
        child.chmod(0o755)
        for name in ("sandbox-exec", "bwrap", "rg", "gh"):
            tool = tools / name
            tool.write_text("#!/bin/sh\nexit " + ("99" if name == "gh" else "0") + "\n")
            tool.chmod(0o755)
        self.checkouts: dict[str, Path] = {}
        for number in (1, 2):
            destination = self.base / f"D{number}"
            controller_fixture.DriverControllerTests.checkout(destination)
            subprocess.run(["git", "-C", str(destination), "switch", "-qc", f"feature/unit-{number}"], check=True)
            self.checkouts[f"U3[{number}]"] = destination
        self.mapping = self.base / "checkouts.json"
        self.mapping.write_text(json.dumps({key: str(path) for key, path in self.checkouts.items()}))
        environment = patch.dict(
            os.environ, HOME=str(home), TMPDIR=str(self.base), PATH=f"{tools}:{os.environ['PATH']}"
        )
        environment.start()
        self.addCleanup(environment.stop)
        control = self.base / "control"
        controller_fixture.DriverControllerTests.checkout(control)
        config = control / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("memory:\n  backend: off\n")
        subprocess.run(["git", "-C", str(control), "add", str(config)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(control),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@test",
                "commit",
                "-qm",
                "fixture config",
            ],
            check=True,
        )
        previous = Path.cwd()
        os.chdir(control)
        self.addCleanup(os.chdir, previous)
        self.addCleanup(self._finish_children)

    def _finish_children(self) -> None:
        self.release.touch()
        attempts = self.case.path.parent / "driver-evidence"
        deadline = time.monotonic() + 3
        while attempts.exists() and time.monotonic() < deadline:
            if all((path / "terminal.json").exists() for path in attempts.iterdir() if (path / "launch.json").exists()):
                return
            time.sleep(0.01)

    def _drive(self, seconds: str = "0") -> subprocess.CompletedProcess[str]:
        return self.case.graph("drive", "--checkout-map", str(self.mapping), "--wait-seconds", seconds)

    def _partial_wave(self) -> Path:
        for _ in range(20):
            run = self._drive()
            self.assertEqual(run.returncode, 0, run.stderr)
            attempts = self.case.path.parent / "driver-evidence"
            first = next((p for p in attempts.iterdir() if (p / "manifest.json").exists()), None)
            if first is not None and len(list(attempts.glob("*/launch.json"))) == 2:
                self.assertEqual(json.loads(run.stdout)["status"], "running")
                self.assertEqual(json.loads((first / "transfer.json").read_bytes())["status"], "quarantined")
                deadline = time.monotonic() + 3
                while self.launches.read_text().splitlines() != ["first", "second"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(self.launches.read_text().splitlines(), ["first", "second"])
                return first
        self.fail("two-worker wave never reached its partially observed state")

    def _destinations(self) -> dict[str, Any]:
        return {key: driver_workspace.destination(path) for key, path in self.checkouts.items()}

    def test_sealed_quarantine_resumes_without_relaunch_or_source_reapply(self) -> None:
        """A failed first worker cannot strand another worker's pending observation."""
        first = self._partial_wave()
        fixed = {name: (first / name).read_bytes() for name in ("manifest.json", "transfer.json")}
        before = self._destinations()
        workspace = json.loads((first / "workspace.json").read_bytes())
        execution = Path(workspace["execution"])
        execution.rename(execution.with_name("retained-unavailable-clone"))
        self.release.touch()
        resumed = self._drive("10")
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads(resumed.stdout)["status"], "recorded")
        self.assertEqual(self._destinations(), before)
        self.assertEqual({name: (first / name).read_bytes() for name in fixed}, fixed)
        self.assertCountEqual(self.launches.read_text().splitlines(), ["first", "second"])
        state = self.case.read()
        self.assertIsNone(state["graph"]["active_wave"])
        for node in state["graph"]["nodes"].values():
            self.assertEqual(node["retry"]["attempts"], 1)
            self.assertEqual(node["outcome"], "pending")
            evidence = node["evidence"][-1]
            manifest = self.case.path.parent / "driver-evidence" / evidence["dispatch_id"] / "manifest.json"
            self.assertEqual(json.loads(manifest.read_bytes())["result"]["outcome"], "failed")

    def test_failed_receipt_tamper_and_live_attempt_change_still_refuse(self) -> None:
        """Skipping preparation must preserve fixed evidence and live-contract validation."""
        first = self._partial_wave()
        original = (first / "transfer.json").read_bytes()
        receipt = json.loads(original)
        receipt["reason"] = "tampered"
        (first / "transfer.json").write_text(json.dumps(receipt))
        before, destinations = self.case.path.read_bytes(), self._destinations()
        refused = self._drive()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("changed", refused.stderr)
        self.assertEqual(self.case.path.read_bytes(), before)
        self.assertEqual(self._destinations(), destinations)
        (first / "transfer.json").write_bytes(original)
        state = self.case.read()
        identifier = first.name
        state["graph"]["dispatches"][identifier]["attempt"] += 1
        self.case.write(state)
        changed = self.case.path.read_bytes()
        refused = self._drive()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("attempt", refused.stderr)
        self.assertEqual(self.case.path.read_bytes(), changed)
        self.assertEqual(self._destinations(), destinations)
        self.assertCountEqual(self.launches.read_text().splitlines(), ["first", "second"])

    def test_unsealed_prelaunch_quarantine_still_refuses(self) -> None:
        """A quarantined preparation cannot acquire a launch by observing the wave."""
        opened = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[3] / "skills/agentic-loop/scripts/graph.py"),
                "begin-driver-wave",
                str(self.case.path),
            ],
            capture_output=True,
        )
        self.assertEqual(opened.returncode, 0, opened.stderr)
        state = self.case.read()
        identifier, record = sorted(state["graph"]["dispatches"].items(), key=lambda item: item[1]["node_id"])[0]
        driver_workspace.prepare_workspace(self.case.path, state, identifier, record, self.checkouts["U3[1]"])
        attempt = self.case.path.parent / "driver-evidence" / identifier
        driver_workspace.phase(attempt, "quarantined", "synthetic prelaunch failure")
        before, destinations = self.case.path.read_bytes(), self._destinations()
        refused = self._drive()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("driver_destination_quarantined", refused.stderr)
        self.assertEqual(self.case.path.read_bytes(), before)
        self.assertEqual(self._destinations(), destinations)
        self.assertFalse((attempt / "launch.json").exists())
        self.assertFalse(self.launches.exists())

    def _assert_sealed_symlink_refused(self, *, parent: bool) -> None:
        first = self._partial_wave()
        before, destinations = self.case.path.read_bytes(), self._destinations()
        fixed = {name: (first / name).read_bytes() for name in ("manifest.json", "transfer.json")}
        launches = self.launches.read_bytes()
        original = first.parent if parent else first
        retained = original.with_name("retained-" + original.name)
        original.rename(retained)
        original.symlink_to(retained, target_is_directory=True)
        refused = self._drive()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("driver artifact path is a symlink", refused.stderr)
        self.assertEqual(self.case.path.read_bytes(), before)
        self.assertEqual(self._destinations(), destinations)
        self.assertEqual({name: (first / name).read_bytes() for name in fixed}, fixed)
        self.assertEqual(self.launches.read_bytes(), launches)

    def test_sealed_attempt_directory_symlink_still_refuses(self) -> None:
        """A completed result cannot bypass the attempt-directory ownership boundary."""
        self._assert_sealed_symlink_refused(parent=False)

    def test_sealed_evidence_parent_symlink_still_refuses(self) -> None:
        """A completed result cannot follow a redirected driver-evidence directory."""
        self._assert_sealed_symlink_refused(parent=True)


if __name__ == "__main__":
    unittest.main()
