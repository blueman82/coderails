"""Receipt writes must stay inside the selected graph state directory."""

from __future__ import annotations

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
