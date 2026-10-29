"""Root materializes a fixed untrusted proposal once and preserves later root edits."""

from __future__ import annotations

import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from hooks.scripts.tests import driver_workspace_test as fixture
from hooks.scripts.tests.graph_convert_test import SCRIPTS
from scripts.sandbox import driver_transfer
from scripts.sandbox import driver_workspace as workspace


def unused_result(_path: Path, _code: int) -> dict[str, Any]:
    """Keep an observing-only fixture out of result recording."""
    return {"outcome": "failed", "evidence": "unused"}


class TransferTests(unittest.TestCase):
    """Real graph authorization and terminal receipts; inert worker, no real provider."""

    def setUp(self) -> None:
        """SetUp."""
        self.context = fixture.WorkspaceTests("test_preparation_is_owned_idempotent_and_leaves_destination_clean")
        self.context.setUp()
        self.addCleanup(self.context.doCleanups)
        controller = importlib.import_module("graph_driver_controller")
        process = importlib.import_module("graph_driver_process")

        def command(prompt: Path, _record: dict[str, Any]) -> tuple[list[str], None, Path]:
            """Command."""
            return [sys.executable, "-c", "pass"], None, prompt

        with patch.object(process, "observe", return_value={"status": "running"}):
            controller.drive_once(
                self.context.case.path,
                "S",
                SCRIPTS["claude"],
                self.context.destination,
                "claude",
                command,
                unused_result,
                prepare_workspace=workspace.prepare_workspace,
            )
        self.attempt = self.context.case.path.parent / "driver-evidence" / self.context.identifier
        self.assertEqual(process.observe(self.attempt, 5), {"status": "finished", "exit_code": 0})
        self.mapping = json.loads((self.attempt / "workspace.json").read_bytes())
        self.clone = Path(self.mapping["execution"])
        self.result: dict[str, Any] = {
            "outcome": "done",
            "evidence": "synthetic proposed source",
            "final_report": {"claims": [], "did_not_verify": []},
        }

    def finish(self) -> dict[str, Any]:
        """Finish."""
        self.assertTrue(hasattr(driver_transfer, "finish_workspace"), "fixed source transfer is not implemented")
        state = self.context.case.read()
        record = state["graph"]["dispatches"][self.context.identifier]
        return driver_transfer.finish_workspace(
            self.context.case.path, state, self.context.identifier, record, self.context.destination, 0, self.result
        )

    def test_transfer_is_fixed_and_resume_keeps_later_root_edits(self) -> None:
        """Transfer is fixed and resume keeps later root edits."""
        payload = b"\0source\xff\r\n"
        (self.clone / "allowed.txt").write_bytes(payload)
        receipt = self.finish()
        self.assertEqual(receipt["status"], "materialized")
        self.assertEqual((self.context.destination / "allowed.txt").read_bytes(), payload)
        (self.clone / "allowed.txt").write_bytes(b"late worker")
        (self.context.destination / "allowed.txt").write_bytes(b"root review edit")
        with patch("scripts.sandbox.source_capture.raw_entries", side_effect=AssertionError("reread source")):
            self.assertEqual(self.finish(), receipt)
        self.assertEqual((self.context.destination / "allowed.txt").read_bytes(), b"root review edit")

    def test_scope_failure_and_partial_write_quarantine_preserve_owner_state(self) -> None:
        """Scope failure and partial write quarantine preserve owner state."""
        (self.clone / "outside.txt").write_text("forbidden proposal")
        receipt = self.finish()
        self.assertEqual(receipt["status"], "quarantined")
        self.assertIn("scope", receipt["reason"])
        self.assertFalse((self.context.destination / "outside.txt").exists())

    def test_foreign_or_stale_context_cannot_consume_transfer(self) -> None:
        """Foreign or stale context cannot consume transfer."""
        state = self.context.case.read()
        before = self.context.case.path.read_bytes()
        for field, value in (("session_id", "foreign"), ("revision", state["revision"] + 1)):
            changed = copy.deepcopy(state)
            changed[field] = value
            record = changed["graph"]["dispatches"][self.context.identifier]
            with self.subTest(field=field), self.assertRaises(ValueError):
                driver_transfer.finish_workspace(
                    self.context.case.path,
                    changed,
                    self.context.identifier,
                    record,
                    self.context.destination,
                    0,
                    self.result,
                )
        self.assertFalse((self.attempt / "transfer.json").exists())
        self.assertEqual(self.context.case.path.read_bytes(), before)

    def test_workspace_changed_after_launch_is_refused_before_capture(self) -> None:
        """An identity-preserving mapping edit cannot authorize destination writes."""
        destination = self.context.destination
        before = driver_transfer.destination_identity(destination)
        original = {
            path.relative_to(destination): path.read_bytes()
            for path in destination.rglob("*")
            if path.is_file() and ".git" not in path.relative_to(destination).parts
        }
        (self.clone / "allowed.txt").write_bytes(b"proposal must not reach root")
        self.mapping["unapproved_field"] = "changed after authorization"
        (self.attempt / "workspace.json").write_text(json.dumps(self.mapping))
        with self.assertRaisesRegex(ValueError, "driver_workspace_mapping_mismatch"):
            self.finish()
        self.assertEqual(driver_transfer.destination_identity(destination), before)
        self.assertEqual(
            {
                path.relative_to(destination): path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file() and ".git" not in path.relative_to(destination).parts
            },
            original,
        )
        for name in ("capture.json", "transfer.json"):
            self.assertFalse((self.attempt / name).exists())
        self.assertEqual(json.loads((self.attempt / "transfer-journal.json").read_bytes())["phase"], "prepared")

    def test_partial_materialization_failure_is_never_reapplied(self) -> None:
        """Partial materialization failure is never reapplied."""
        (self.clone / "allowed.txt").write_text("proposal")

        def partial(*_args: object) -> None:
            """Partial."""
            (self.context.destination / "partial.txt").write_text("retained failure")
            raise OSError("injected interruption")

        with patch("scripts.sandbox.source_materialize.apply", side_effect=partial):
            receipt = self.finish()
        self.assertEqual(receipt["status"], "quarantined")
        self.assertEqual((self.context.destination / "partial.txt").read_text(), "retained failure")
        with patch("scripts.sandbox.source_materialize.apply", side_effect=AssertionError("reapplied")):
            self.assertEqual(self.finish(), receipt)

    def test_destination_drift_quarantines_without_overwrite(self) -> None:
        """Destination drift quarantines without overwrite."""
        (self.clone / "allowed.txt").write_text("proposal")
        (self.context.destination / "owner.txt").write_text("retain")
        receipt = self.finish()
        self.assertEqual(receipt["status"], "quarantined")
        self.assertEqual((self.context.destination / "owner.txt").read_text(), "retain")
        self.assertFalse((self.context.destination / "allowed.txt").exists())


if __name__ == "__main__":
    unittest.main()
