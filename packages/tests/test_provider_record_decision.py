"""`graph.py record-decision` appends one typed ledger row identically through both providers' real CLIs."""

from __future__ import annotations

import json
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from packages.tests.test_provider_controller_commands import LOOP, SESSION, Controller, ControllerCase

ROW_KEYS = {"seq", "phase", "decision", "chosen", "revision", "recorded_at"}


def decide(c: Controller, *extra: str, session: str = SESSION) -> subprocess.CompletedProcess[str]:
    """Run `record-decision` with the required typed flags."""
    return c.run("record-decision", "--session", session, "--phase", "2.6", "--decision", "disposition", *extra)


class RecordDecisionTests(ControllerCase):
    """Typed flags, ownership, status resolution and concurrent appends."""

    def started(self, c: Controller) -> None:
        """A started loop with one unit."""
        self.assertEqual(c.start().returncode, 0)

    def test_row_has_the_typed_fields_and_the_dashboard_keys(self) -> None:
        """Typed fields, optional keys only when given, string phase/decision (the dashboard reader's keys)."""
        for c in self.each():
            self.started(c)
            before = c.read()["revision"]
            first = decide(c, "--chosen", "clean-break")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = decide(c, "--chosen", "preserve-compat", "--flip-condition", "ticket OPS-1 closes")
            self.assertEqual(second.returncode, 0, second.stderr)
            rows: list[dict[str, Any]] = c.read()["decisions_absorbed"]
            self.assertEqual(set(rows[0]), ROW_KEYS)
            self.assertEqual(set(rows[1]), ROW_KEYS | {"flip_condition"})
            self.assertEqual([row["seq"] for row in rows], [1, 2])
            self.assertEqual(
                (rows[0]["phase"], rows[0]["decision"], rows[0]["chosen"]), ("2.6", "disposition", "clean-break")
            )
            self.assertEqual(rows[1]["flip_condition"], "ticket OPS-1 closes")
            self.assertEqual(rows[0]["revision"], before)
            self.assertEqual(c.read()["revision"], before)  # the ledger never invalidates frozen evals
            datetime.fromisoformat(rows[0]["recorded_at"])
            self.assertEqual(json.loads(first.stdout), rows[0])
            self.assertEqual(c.codes("record-decision"), ["decision_recorded"] * 2)

    def test_legacy_rows_are_kept_and_numbering_continues(self) -> None:
        """Hand-written {phase, decision} rows survive untouched; the first typed row is seq 1."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["decisions_absorbed"] = [{"phase": "2.5", "decision": "old prose"}]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(decide(c, "--chosen", "x").returncode, 0)
            rows = c.read()["decisions_absorbed"]
            self.assertEqual(rows[0], {"phase": "2.5", "decision": "old prose"})
            self.assertEqual(rows[1]["seq"], 1)

    def test_refusals_leave_state_bytes_unchanged(self) -> None:
        """Foreign session, blank fields, a torn ledger and an unknown or settled status each refuse with a code."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["worker_statuses"] = [{"seq": 1, "decision_pending": False}, {"seq": 2, "decision_pending": True}]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            cases = (
                (decide(c, "--chosen", "x", session="someone-else"), "record_decision_refused_foreign"),
                (decide(c, "--chosen", "  "), "record_decision_refused_field"),
                (decide(c, "--chosen", "x", "--flip-condition", " "), "record_decision_refused_field"),
                (decide(c, "--chosen", "x", "--worker-status-seq", "9"), "record_decision_refused_status"),
                (decide(c, "--chosen", "x", "--worker-status-seq", "1"), "record_decision_refused_status"),
            )
            for result, code in cases:
                before = c.path.read_bytes()
                self.refused(result, code)
                self.assertEqual(c.path.read_bytes(), before, code)
            state["decisions_absorbed"] = "torn"
            c.path.write_text(json.dumps(state), encoding="utf-8")
            before = c.path.read_bytes()
            self.refused(decide(c, "--chosen", "x"), "record_decision_refused_state")
            self.assertEqual(c.path.read_bytes(), before)

    def test_worker_status_seq_marks_that_status_resolved(self) -> None:
        """Only the named worker_statuses row flips to resolved, and the row records which status it answered."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["worker_statuses"] = [
                {
                    "seq": n,
                    "status": "NEEDS_DECISION",
                    "payload": {"options": ["allow", "deny"]},
                    "decision_pending": True,
                }
                for n in (1, 2)
            ]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            done = decide(c, "--chosen", "allow", "--worker-status-seq", "2")
            self.assertEqual(done.returncode, 0, done.stderr)
            after = c.read()
            self.assertEqual([s["decision_pending"] for s in after["worker_statuses"]], [True, False])
            self.assertEqual(after["worker_statuses"][1]["resolved_by_decision"], 1)
            self.assertEqual(after["decisions_absorbed"][0]["worker_status_seq"], 2)

    def test_status_answers_are_bound_to_the_pending_question(self) -> None:
        """A chosen outside the status options, or an approval-gate answer without --human-answer, refuses unchanged."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["worker_statuses"] = [
                {"seq": 1, "status": "NEEDS_DECISION", "payload": {"options": ["a", "b"]}, "decision_pending": True},
                {"seq": 2, "status": "OUTSIDE_SCOPE", "payload": {}, "decision_pending": True},
            ]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            cases = (
                (decide(c, "--chosen", "invented", "--worker-status-seq", "1"), "record_decision_refused_chosen"),
                (decide(c, "--chosen", "allow", "--worker-status-seq", "2"), "record_decision_refused_human"),
            )
            for result, code in cases:
                before = c.path.read_bytes()
                self.refused(result, code)
                self.assertEqual(c.path.read_bytes(), before, code)
            self.assertEqual(decide(c, "--chosen", "a", "--worker-status-seq", "1").returncode, 0)
            self.assertEqual(decide(c, "--chosen", "allow", "--worker-status-seq", "2", "--human-answer").returncode, 0)

    def test_concurrent_appends_all_land_with_distinct_seqs(self) -> None:
        """Six simultaneous CLI calls under the state lock: six rows, seq 1..6, no lost update."""
        for c in self.each():
            self.started(c)
            with ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(decide, c, "--chosen", f"c{n}") for n in range(6)]
                results = [future.result() for future in futures]
            self.assertEqual([r.returncode for r in results], [0] * 6, [r.stderr for r in results])
            rows = c.read()["decisions_absorbed"]
            self.assertEqual(sorted(row["seq"] for row in rows), [1, 2, 3, 4, 5, 6])
            self.assertEqual({row["chosen"] for row in rows}, {f"c{n}" for n in range(6)})

    def test_malformed_or_ambiguous_pending_status_cannot_be_resolved(self) -> None:
        """Unknown status kinds, duplicate ids and malformed options cannot clear the decision gate."""
        pending = {"seq": 1, "status": "NEEDS_DECISION", "payload": {"options": ["a", "b"]}, "decision_pending": True}
        cases = [
            [{**pending, "status": "UNKNOWN"}],
            [pending, pending],
            [{**pending, "payload": {"options": "abc"}}],
            [{**pending, "payload": {"options": ["a"]}}],
            [{**pending, "seq": True}],
        ]
        for c in self.each():
            self.started(c)
            original = c.read()
            for statuses in cases:
                state = {**original, "worker_statuses": statuses}
                c.path.write_text(json.dumps(state), encoding="utf-8")
                before = c.path.read_bytes()
                self.refused(decide(c, "--chosen", "a", "--worker-status-seq", "1"), "record_decision_refused_status")
                self.assertEqual(c.path.read_bytes(), before)

    def test_loop_identity_is_untouched(self) -> None:
        """The command writes only the ledger (and the resolved flag): session, loop and graph keep their values."""
        for c in self.each():
            self.started(c)
            before = c.read()
            self.assertEqual(decide(c, "--chosen", "x").returncode, 0)
            after = c.read()
            after.pop("decisions_absorbed")
            self.assertEqual(
                {k: v for k, v in after.items() if k != "updated_at"},
                {k: v for k, v in before.items() if k != "updated_at"},
            )
            self.assertEqual((after["session_id"], after["loop_id"]), (SESSION, LOOP))


if __name__ == "__main__":
    unittest.main()
