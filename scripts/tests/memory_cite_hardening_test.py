"""Cite hardening: empty default role, own-session quote-only/cite checks, adjacent short approvals, K-id and scope.

Each acceptance test has a control that flips the one input it proves. Hermetic fake muninn, temp store.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.lib import memory_cite  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT, PROPOSAL, SESSION, StoreCase  # noqa: E402

ADAPTER = str(REPO / "scripts/lib/memory_adapter.py")


class Hardening(StoreCase):
    """Findings of the lane D unit U2 review."""

    with_store = True

    def cli(self, *extra: str, session: str = SESSION) -> tuple[int, dict[str, object]]:
        """Run the adapter CLI `add` for loop L1; return (rc, stdout JSON)."""
        base = [sys.executable, ADAPTER, "add", "--type", "lesson", "--loop", "L1", "--claim", "c"]
        base += ["--session", session]
        env = {**os.environ, "CLAUDE_CODE_SESSION_ID": SESSION}
        p = subprocess.run([*base, *extra], capture_output=True, text=True, env=env)
        return p.returncode, json.loads(p.stdout)

    def test_default_record_declares_no_anchor(self) -> None:
        """A Record with no declared role is cite_not_user; declaring the user prompt passes (control)."""
        bare = ma.Record("loop", "lesson", "c", f"claude:{SESSION}:2.1", PROPOSAL, loop_id="L1")
        self.assertEqual(ma.validate(bare), "cite_not_user")
        bare.cite_role, bare.cite_kind = "user", "prompt"
        self.assertIsNone(ma.validate(bare))

    def test_quote_only_must_sit_in_own_user_prompt(self) -> None:
        """Quote-only: a made-up or assistant-authored quote is cite_not_user; a real prompt quote writes."""
        self.assertEqual(self.cli("--quote", "agent invented this quote text"), (3, {"degraded": "cite_not_user"}))
        self.assertEqual(self.cli("--quote", PROPOSAL), (3, {"degraded": "cite_not_user"}))
        self.assertEqual(self.cli("--quote", "targeted tests before committing"), (0, {"ok": True, "id": "K1"}))
        self.assertEqual(self.cli("--quote", PROMPT, session=""), (3, {"degraded": "cite_unresolved"}))

    def test_cite_must_be_in_the_callers_own_session(self) -> None:
        """A user prompt of another session is cite_not_own_session; the same ref in the own session writes."""
        self.assertEqual(
            self.cli("--cite", "claude:other:1.1", "--quote", PROMPT), (3, {"degraded": "cite_not_own_session"})
        )
        self.assertEqual(self.cli("--cite", f"claude:{SESSION}:1.1", "--quote", PROMPT), (0, {"ok": True, "id": "K1"}))

    def test_approval_must_be_short_and_adjacent(self) -> None:
        """An approval with a user prompt between it and the reply, or a long one, is cite_bad_approval."""
        self.assertEqual(self.cli("--approval", f"claude:{SESSION}:4.1"), (3, {"degraded": "cite_bad_approval"}))
        self.assertEqual(self.cli("--approval", f"claude:{SESSION}:3.1"), (0, {"ok": True, "id": "K1"}))
        event = {"ref": "claude:s:2.1", "role": "user", "kind": "prompt", "preview": "y" * 81}
        reply = {"ref": "claude:s:1.1", "role": "assistant", "kind": "reply", "preview": "proposal"}
        self.assertEqual(memory_cite.approved_reply({"events": [reply, event]}, "claude:s:2.1"), "cite_bad_approval")
        event["preview"] = "y" * 80
        self.assertIsInstance(memory_cite.approved_reply({"events": [reply, event]}, "claude:s:2.1"), tuple)

    def test_supersedes_must_be_a_kid(self) -> None:
        """A non-K<n> supersedes/contradicts is bad_record before any spawn; K1 passes validation (control)."""
        self.assertEqual(ma.validate(self.record("c", supersedes="1; x")), "bad_record")
        self.assertEqual(ma.validate(self.record("c", contradicts="K1,K2")), "bad_record")
        self.assertIsNone(ma.validate(self.record("c", supersedes="K1")))

    def test_cross_loop_supersede_is_refused_by_muninn(self) -> None:
        """Verified boundary: muninn refuses a supersede across scopes, so another loop's record is not retired."""
        self.written(ma.add(self.record("other loop", loop_id="L2")))
        refused = ma.add(self.record("take over", supersedes="K1"))
        self.assertEqual(refused, ma.Degraded("refused_bad_supersedes"))

    def test_list_keeps_only_the_requested_scope(self) -> None:
        """A global record is returned for scope user and not for scope project (it was mislabeled before)."""
        self.written(ma.add(self.record("global one", scope="user", loop_id=None)))
        got_user, got_project = ma.list_records("user"), ma.list_records("project")
        self.assertEqual([r.claim for r in got_user], ["global one"])  # type: ignore[union-attr]
        self.assertEqual(got_project, [])


if __name__ == "__main__":
    unittest.main()
