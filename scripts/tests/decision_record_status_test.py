"""Atomic typed decision status resolution through both provider locks."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from unittest import mock

from hooks.scripts.lib.graph_executor import transition as claude_transition
from scripts.lib import decision_record as dr
from scripts.tests.decision_record_test import PROVIDERS, Base, decision_pending, worker_status
from scripts.tests.fake_muninn_case import SESSION


class LocalFirstAndChain(Base):
    """(a) both providers append hashed, chained rows with the dashboard shape; (g) a clean chain verifies."""

    def test_both_providers_append_chained_rows(self) -> None:
        """Two calls per provider: seq, hashes, muninn field, prev link, {phase, decision} intact."""
        for name, tr in PROVIDERS:
            with self.subTest(provider=name):
                self.put({**self.state(), "decisions_absorbed": []})
                first = self.rec(tr, "2.5", "adopt shape A", flip_condition="owner objects")
                second = self.rec(tr, "2.6", "clean-break", unit="U1")
                rows = self.decisions()
                self.assertEqual((first["seq"], second["seq"]), (1, 2))
                self.assertEqual([r["seq"] for r in rows], [1, 2])
                self.assertEqual((rows[0]["phase"], rows[0]["decision"]), ("2.5", "adopt shape A"))
                self.assertEqual(rows[0]["flip_condition"], "owner objects")
                self.assertEqual(rows[1]["unit"], "U1")
                self.assertEqual(rows[0]["prev_sha256"], dr.GENESIS)
                self.assertEqual(rows[1]["prev_sha256"], rows[0]["row_sha256"])
                self.assertEqual(rows[0]["muninn"]["state"], "pending")
                self.assertTrue(rows[0]["muninn"]["request_id"].startswith("R_"))
                self.assertEqual(dr.verify_chain(rows), [])

    def test_worker_answer_is_one_hashed_row_and_one_resolved_status(self) -> None:
        """Each provider commits the answer and status together, then syncs outside the graph lock."""
        for name, tr in PROVIDERS:
            with self.subTest(provider=name):
                state = self.state()
                state["decisions_absorbed"] = []
                state["worker_statuses"] = [
                    {
                        "seq": 1,
                        "node": "U3[1]",
                        "status": "NEEDS_DECISION",
                        "payload": {"options": ["allow", "deny"]},
                        "decision_pending": True,
                    }
                ]
                self.put(state)
                active = False

                def single_lock(path: Path, fn: Any, transition: Any = tr) -> dict[str, Any]:  # noqa: ANN401
                    nonlocal active
                    self.assertFalse(active, "provider transition nested")
                    active = True
                    try:
                        return transition(path, fn)  # type: ignore[no-any-return]
                    finally:
                        active = False

                out = self.rec(
                    single_lock,
                    chosen="allow",
                    worker_status_seq=1,
                    status_resolver=worker_status.resolve_pending,
                )
                after = self.state()
                self.assertEqual(out["exit_code"], 3)
                self.assertEqual(out["muninn"]["state"], "pending")
                self.assertEqual(len(after["decisions_absorbed"]), 1)
                self.assertEqual(dr.verify_chain(after["decisions_absorbed"], after["chain_started_seq"]), [])
                self.assertEqual(after["decisions_absorbed"][0]["worker_status_seq"], 1)
                self.assertEqual(after["decisions_absorbed"][0]["chosen"], "allow")
                self.assertEqual(after["worker_statuses"][0]["resolved_by_decision"], 1)
                self.assertTrue(decision_pending(after, "U3[1]"))
                self.assertEqual(
                    self.muninn(
                        "learn",
                        "complete",
                        out["muninn"]["request_id"],
                        "--kind",
                        "decision",
                        "--content",
                        "2.5: adopt shape A",
                    )[0],
                    0,
                )
                self.assertEqual(dr.flush_pending(self.path, SESSION, transition=tr)["exit_code"], 0)
                self.assertFalse(decision_pending(self.state(), "U3[1]"))

    def test_unresolved_memory_sync_keeps_the_answered_node_blocked(self) -> None:
        """A local hashed answer survives a store outage but cannot release the next wave."""
        state = self.state()
        state["worker_statuses"] = [
            {
                "seq": 1,
                "node": "U3[1]",
                "status": "NEEDS_DECISION",
                "payload": {"options": ["allow", "deny"]},
                "decision_pending": True,
            }
        ]
        self.put(state)
        with mock.patch.object(dr, "sync_row", return_value={"state": "unknown", "reason_code": "muninn_error"}):
            out = self.rec(
                chosen="allow",
                worker_status_seq=1,
                status_resolver=worker_status.resolve_pending,
            )
        after = self.state()
        self.assertEqual((out["recorded"], out["exit_code"]), (True, 3))
        self.assertEqual(dr.verify_chain(after["decisions_absorbed"], after["chain_started_seq"]), [])
        self.assertFalse(after["worker_statuses"][0]["decision_pending"])
        self.assertTrue(decision_pending(after, "U3[1]"))

    def test_control_unchained_row_would_fail_the_link_assert(self) -> None:
        """Negative control: a row whose prev link is wrong is reported by verify_chain."""
        self.rec()
        self.rec(phase="2.6", text="second")
        rows = self.decisions()
        rows[1]["prev_sha256"] = dr.GENESIS
        self.assertEqual({o["seq"] for o in dr.verify_chain(rows)}, {2})

    def test_refusals_write_nothing(self) -> None:
        """(f) a wrong session, a blank decision and a blank phase are refused and the file is untouched."""
        before = self.path.read_bytes()
        cases = (
            (
                dr.record(
                    self.path,
                    "other",
                    "2.5",
                    "x",
                    expected_loop_id="L1",
                    expected_revision=self.state()["revision"],
                    transition=claude_transition,
                ),
                "decision_wrong_session",
            ),
            (self.rec(text="   "), "decision_blank_decision"),
            (self.rec(phase=" "), "decision_blank_phase"),
        )
        for out, code in cases:
            self.assertEqual((out["recorded"], out["reason_code"], out["exit_code"]), (False, code, 2))
        self.assertEqual(self.path.read_bytes(), before)
        traced = [r["reason_code"] for r in self.trace() if r["command"] == "decision.record"]
        self.assertEqual(traced, [cases[1][1], cases[2][1]])  # the wrong session traces under its own session id

    def test_control_pure_add_does_not_mutate_its_input(self) -> None:
        """add_decision returns a new state; the caller's dict is unchanged."""
        before = copy.deepcopy(self.state())
        out = dr.add_decision(self.state(), SESSION, "2.5", "x", "L1", self.state()["revision"])
        self.assertEqual(self.state(), before)
        self.assertEqual(len(out["state"]["decisions_absorbed"]), 1)
