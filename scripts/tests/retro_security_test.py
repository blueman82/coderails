"""Retro assembly must keep output and receipts inside the verified state directory."""

from __future__ import annotations

import json

from scripts.lib import retro, teardown_steps
from scripts.tests.fake_muninn_case import SESSION
from scripts.tests.retro_test import Base


class RetroWriteSafety(Base):
    """Exercise the real assembler with unsafe state and receipt paths."""

    def test_assemble_refuses_linked_state_directory(self) -> None:
        """A linked state path cannot publish retro.json in its target directory."""
        self.ready()
        retro_file = self.dir / "retro.json"
        retro_file.unlink()
        alias = self.tmp / "linked-state"
        alias.symlink_to(self.dir, target_is_directory=True)
        payload, code = retro.assemble(alias, SESSION)
        self.assertEqual(code, 2, payload)
        self.assertFalse(retro_file.exists())

    def test_assemble_refuses_failed_receipt_record(self) -> None:
        """A refused receipt cannot publish retro.json without a matching earlier row."""
        self.ready()
        retro_file = self.dir / "retro.json"
        retro_file.unlink()
        receipt = self.dir / teardown_steps.NAME
        rows = [row for row in teardown_steps.read_rows(self.dir) if row["step"] != "retro_assembled"]
        receipt.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        lock = self.dir / f"{teardown_steps.NAME}.lock"
        lock.unlink()
        lock.symlink_to(self.tmp / "outside-lock")
        payload, code = retro.assemble(self.dir, SESSION)
        self.assertEqual(code, 2, payload)
        self.assertFalse(retro_file.exists())
