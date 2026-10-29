"""Required teardown rows keep the loop and session that produced them."""

from __future__ import annotations

import copy
import json

from scripts.lib import retro_check, teardown_steps
from scripts.tests.retro_test import Base


class TeardownIdentity(Base):
    """A foreign source row cannot authorize this loop's retrospective."""

    def test_retro_identity_and_status_match_owned_progress(self) -> None:
        """The Claude completion gate rejects a copied or edited retro envelope."""
        self.ready()
        original = self.retro()
        for field, value in (("session_id", "foreign"), ("loop_id", "other"), ("status", "in-progress")):
            self.rewrite_retro(**{field: value})
            with self.assertRaisesRegex(ValueError, rf"retro_source_mismatch.*retro\.{field}"):
                self.gate()
            (self.dir / "retro.json").write_text(json.dumps(original))
        self.assertEqual(self.gate(), [])

    def test_required_teardown_rows_keep_session_and_loop_identity(self) -> None:
        """A matching evidence hash cannot authorize a foreign teardown row."""
        self.ready()
        original = teardown_steps.read_rows(self.dir)
        for step in ("proof_run", "decisions_flushed", "retro_assembled"):
            rows = copy.deepcopy(original)
            row = next(item for item in reversed(rows) if item["step"] == step)
            row["session_id"] = "foreign"
            row["loop_id"] = "other"
            (self.dir / teardown_steps.NAME).write_text("".join(json.dumps(item) + "\n" for item in rows))
            self.assertEqual(self.assemble()[0], 0)
            with self.assertRaisesRegex(ValueError, rf"retro_steps_missing.*{step}"):
                self.gate()
            (self.dir / teardown_steps.NAME).write_text("".join(json.dumps(item) + "\n" for item in original))
            self.rewrite_retro(source_hashes=retro_check.source_hashes(self.state(), self.dir))
            self.assertEqual(self.gate(), [])

    def test_broken_chain_cannot_be_reassembled_after_preparation(self) -> None:
        """A changed decision row cannot replace the decision flush bound by preparation."""
        self.ready()
        state = self.state()
        state["decisions_absorbed"][1]["decision"] = "edited"
        self.put(state)
        code, result = self.assemble()
        self.assertEqual((code, result["reason_code"]), (2, "decisions_not_flushed"))
        with self.assertRaisesRegex(ValueError, r"retro_source_mismatch.*progress.decisions_absorbed"):
            self.gate()
        forged = self.retro()
        forged["source_hashes"] = retro_check.source_hashes(state, self.dir)
        forged["decisions_absorbed"] = state["decisions_absorbed"]
        (self.dir / "retro.json").write_text(json.dumps(forged))
        with self.assertRaisesRegex(ValueError, r"retro_decisions_chain_broken.*seq 2 \(bad_hash\)"):
            self.gate()
