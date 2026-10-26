"""Receipt writes must stay inside the selected graph state directory."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.lib import teardown_steps


class TeardownReceiptSafety(unittest.TestCase):
    """Check that append receipts cannot follow filesystem aliases."""

    def test_receipt_and_directory_symlinks_are_refused(self) -> None:
        """Refuse both receipt and directory links, then append to a normal state."""
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            state = root / "state"
            state.mkdir()
            (state / "progress.json").write_text('{"loop_id":"L1"}', encoding="utf-8")
            receipt = state / teardown_steps.NAME
            outside = root / "outside.jsonl"
            for existing in (False, True):
                with self.subTest(existing=existing):
                    if existing:
                        outside.write_bytes(b"")
                    receipt.symlink_to(outside)
                    try:
                        self.assertFalse(teardown_steps.record(state, "proof_run", "s1", "L1", "a"))
                        self.assertEqual(outside.read_bytes() if outside.exists() else None, b"" if existing else None)
                    finally:
                        receipt.unlink()
            alias = root / "linked-state"
            alias.symlink_to(state, target_is_directory=True)
            self.assertFalse(teardown_steps.record(alias, "proof_run", "s1", "L1", "a"))
            self.assertTrue(teardown_steps.record(state, "proof_run", "s1", "L1", "a"))
            self.assertEqual([row["step"] for row in teardown_steps.read_rows(state)], ["proof_run"])

    def test_hardlink_and_linked_ancestor_are_refused(self) -> None:
        """A receipt must not write through another name for an outside path."""
        with tempfile.TemporaryDirectory() as scratch:
            root = Path(scratch)
            state = root / "real" / "state"
            state.mkdir(parents=True)
            (state / "progress.json").write_text('{"loop_id":"L1"}', encoding="utf-8")
            outside = root / "outside.jsonl"
            outside.write_bytes(b"")
            receipt = state / teardown_steps.NAME
            os.link(outside, receipt)
            self.assertFalse(teardown_steps.record(state, "proof_run", "s1", "L1", "a"))
            self.assertEqual(outside.read_bytes(), b"")
            receipt.unlink()

            alias = root / "alias"
            alias.symlink_to(root / "real", target_is_directory=True)
            self.assertFalse(teardown_steps.record(alias / "state", "proof_run", "s1", "L1", "a"))
            self.assertFalse(receipt.exists())
            self.assertTrue(teardown_steps.record(state, "proof_run", "s1", "L1", "a"))

    def test_valid_unterminated_row_gets_separator_before_append(self) -> None:
        """Keep a valid final row readable when the next step is recorded."""
        with tempfile.TemporaryDirectory() as scratch:
            state = Path(scratch) / "state"
            state.mkdir()
            (state / "progress.json").write_text('{"loop_id":"L1"}', encoding="utf-8")
            self.assertTrue(teardown_steps.record(state, "proof_run", "s1", "L1", "a"))
            receipt = state / teardown_steps.NAME
            receipt.write_bytes(receipt.read_bytes().rstrip(b"\n"))
            self.assertTrue(teardown_steps.record(state, "decisions_flushed", "s1", "L1", "b"))
            self.assertEqual(
                [row["step"] for row in teardown_steps.read_rows(state)], ["proof_run", "decisions_flushed"]
            )
            receipt.write_bytes(b'{"step":')
            self.assertFalse(teardown_steps.record(state, "orders_prepared", "s1", "L1", "c"))
            self.assertEqual(receipt.read_bytes(), b'{"step":')
