"""Preparation binds a private execution clone to a pristine root destination."""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hooks.scripts.tests.graph_convert_test import SCRIPTS, Case
from packages.tests import test_driver_controller as fixture
from packages.tests.test_driver_authorize import frozen_evals


def unused_result(_path: Path, _code: int) -> dict[str, Any]:
    """Keep an observing-only fixture out of result recording."""
    return {"outcome": "failed", "evidence": "unused"}


class WorkspaceTests(unittest.TestCase):
    """Run public graph setup and trusted local Git preparation only."""

    def setUp(self) -> None:
        """SetUp."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.destination = self.base / "destination"
        fixture.DriverControllerTests.checkout(self.destination)
        subprocess.run(["git", "-C", str(self.destination), "switch", "-qc", "feature/probe"], check=True)
        config = self.destination / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("memory:\n  backend: off\n")
        subprocess.run(["git", "-C", str(self.destination), "add", str(config)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
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
        os.chdir(self.destination)
        self.addCleanup(os.chdir, previous)
        self.home = self.base / "home"
        config = self.home / ".coderails/workflow.config.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("memory:\n  backend: off\n")
        credential = self.home / ".coderails/worker_credential"
        credential.write_text("CLAUDE_CODE_OAUTH_TOKEN=synthetic-dedicated-secret\n")
        credential.chmod(0o600)
        environment = patch.dict(os.environ, {"HOME": str(self.home), "TMPDIR": str(self.base)})
        environment.start()
        self.addCleanup(environment.stop)
        runtime = patch("scripts.sandbox.containment.runtime_present", return_value=True)
        runtime.start()
        self.addCleanup(runtime.stop)

        self.case = Case("claude", self.base)
        fixture.DriverControllerTests.scoped(self.case)
        state = self.case.read()
        state["work_units"]["1"].update(manifest=["allowed.txt"], write_scope=["allowed.txt"])
        self.case.write(state)
        self.assertEqual(self.case.graph("convert").returncode, 0)
        self.assertEqual(self.case.graph("cutover-driver").returncode, 0)
        assigned = self.case.graph(
            "assign-worktree", "--loop-id", "L", "--unit", "1", "--worktree", str(self.destination)
        )
        self.assertEqual(assigned.returncode, 0, assigned.stderr)
        self.case.path.with_name("evals.json").write_text(json.dumps(frozen_evals()))
        opened = subprocess.run(
            [sys.executable, str(SCRIPTS["claude"]), "begin-driver-wave", str(self.case.path)], capture_output=True
        )
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.state = self.case.read()
        self.identifier, self.record = next(iter(self.state["graph"]["dispatches"].items()))

    def prepare(self) -> dict[str, Any]:
        """Load the new consumer only after confirming it exists."""
        self.assertIsNotNone(importlib.util.find_spec("scripts.sandbox.driver_workspace"))
        module = importlib.import_module("scripts.sandbox.driver_workspace")
        return cast(
            dict[str, Any],
            module.prepare_workspace(self.case.path, self.state, self.identifier, self.record, self.destination),
        )

    def test_preparation_is_owned_idempotent_and_leaves_destination_clean(self) -> None:
        """C exists before rendering; D retains its exact source, index and HEAD."""
        workspace = self.prepare()
        self.assertNotEqual(workspace["execution"], str(self.destination))
        self.assertTrue(Path(workspace["execution"]).is_dir())
        self.assertEqual(workspace["destination"], str(self.destination))
        self.assertEqual(workspace["dispatch_id"], self.identifier)
        self.assertEqual(self.prepare(), workspace)
        status = subprocess.check_output(["git", "-C", str(self.destination), "status", "--porcelain"])
        self.assertEqual(status, b"")

    def test_controller_prepares_before_prompt_and_observes_destination(self) -> None:
        """The authorized prompt names C while the process receipt continues to observe D."""
        controller = importlib.import_module("graph_driver_controller")
        process = importlib.import_module("graph_driver_process")
        workspace_module = importlib.import_module("scripts.sandbox.driver_workspace")
        seen: list[dict[str, Any]] = []

        def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
            """Command."""
            workspace = json.loads((prompt.parent / "workspace.json").read_bytes())
            seen.append(workspace)
            text = prompt.read_text()
            self.assertIn("Checkout: " + workspace["execution"], text)
            self.assertIn("Root publication checkout: " + str(self.destination), text)
            self.assertNotEqual(workspace["execution"], workspace["destination"])
            return [sys.executable, "-c", "pass"], None, prompt

        with (
            patch.object(process, "start") as started,
            patch.object(process, "observe", return_value={"status": "running"}),
        ):
            report = controller.drive_once(
                self.case.path,
                "S",
                SCRIPTS["claude"],
                self.destination,
                "claude",
                command,
                unused_result,
                prepare_workspace=workspace_module.prepare_workspace,
            )
        self.assertEqual(report["status"], "running")
        self.assertEqual(started.call_args.args[2], self.destination)
        self.assertEqual(len(seen), 1)
        self.assertIn(seen[0]["execution"].encode(), started.call_args.kwargs["stdin_bytes"])

    def test_prepared_launcher_executes_c_with_authorized_stdin(self) -> None:
        """An inert npx boundary observes C and exact bytes; no provider or OS sandbox is qualified."""
        controller = importlib.import_module("graph_driver_controller")
        process = importlib.import_module("graph_driver_process")
        workspace_module = importlib.import_module("scripts.sandbox.driver_workspace")
        launcher = importlib.import_module("scripts.sandbox.spawn_sandboxed_worker")
        self.assertTrue(hasattr(launcher, "launch_prepared"), "prepared execution is not implemented")

        def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
            """Command."""
            return [sys.executable, "-c", "pass"], None, prompt

        with patch.object(process, "start"), patch.object(process, "observe", return_value={"status": "running"}):
            controller.drive_once(
                self.case.path,
                "S",
                SCRIPTS["claude"],
                self.destination,
                "claude",
                command,
                unused_result,
                prepare_workspace=workspace_module.prepare_workspace,
            )
        attempt = self.case.path.parent / "driver-evidence" / self.identifier
        workspace = json.loads((attempt / "workspace.json").read_bytes())
        expected = (attempt / "prompt.txt").read_bytes()
        tools = self.base / "bin"
        tools.mkdir()
        observed = self.base / "observed.json"
        shim = tools / "npx"
        shim.write_text(
            f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
            f"Path({str(observed)!r}).write_text(json.dumps({{'cwd':os.getcwd(),'stdin':sys.stdin.buffer.read().hex()}}))\n"
        )
        shim.chmod(0o755)
        with (
            patch.dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}"),
            patch.object(sys, "stdin", io.TextIOWrapper(io.BytesIO(expected))),
        ):
            self.assertEqual(launcher.launch_prepared(attempt / "workspace.json", "fixture", "loop-worker"), 0)
        result = json.loads(observed.read_text())
        self.assertEqual(result["cwd"], workspace["execution"])
        self.assertEqual(bytes.fromhex(result["stdin"]), expected)

    def test_dirty_destination_is_refused_without_overwriting(self) -> None:
        """An untracked destination file cannot become an implicit input or be erased."""
        self.assertIsNotNone(importlib.util.find_spec("scripts.sandbox.driver_workspace"))
        (self.destination / "owner.txt").write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "destination"):
            self.prepare()
        self.assertEqual((self.destination / "owner.txt").read_bytes(), b"keep")

    def _assert_raw_drift_refused(self, kind: str) -> None:
        module = importlib.import_module("scripts.sandbox.driver_workspace")
        (self.destination / ".gitignore").write_text("__pycache__/\n")
        (self.destination / "tracked.txt").write_text("trusted baseline")
        subprocess.run(["git", "-C", str(self.destination), "add", ".gitignore", "tracked.txt"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.destination),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=t@example.test",
                "commit",
                "-qm",
                "tracked baseline",
            ],
            check=True,
        )
        if kind == "ignored":
            cache = self.destination / "__pycache__"
            cache.mkdir()
            (cache / "retained.pyc").write_bytes(b"owner cache")
        else:
            subprocess.run(
                ["git", "-C", str(self.destination), "update-index", "--assume-unchanged", "tracked.txt"],
                check=True,
            )
            (self.destination / "tracked.txt").write_text("hidden owner edit")
        before = module.destination(self.destination)
        source = {
            p.relative_to(self.destination): p.read_bytes()
            for p in self.destination.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(self.destination).parts
        }
        with patch("scripts.sandbox.containment.runtime_present", return_value=True) as runtime:
            with self.assertRaisesRegex(ValueError, "driver_destination_source_drift"):
                self.prepare()
            runtime.assert_not_called()
        self.assertEqual(module.destination(self.destination), before)
        self.assertEqual(
            {
                p.relative_to(self.destination): p.read_bytes()
                for p in self.destination.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(self.destination).parts
            },
            source,
        )
        self.assertFalse((Path(before["admin"]) / "coderails-driver-reservation.json").exists())
        attempt = self.case.path.parent / "driver-evidence" / self.identifier
        for name in ("workspace.json", "launch.json", "transfer-journal.json"):
            self.assertFalse((attempt / name).exists())

    def test_ignored_destination_products_refuse_before_reservation(self) -> None:
        """Ignored root products are retained and refused before a worker starts."""
        self._assert_raw_drift_refused("ignored")

    def test_index_hidden_destination_edit_refuses_before_reservation(self) -> None:
        """An index hint cannot hide raw tracked drift from preparation."""
        self._assert_raw_drift_refused("assume_unchanged")


if __name__ == "__main__":
    unittest.main()
