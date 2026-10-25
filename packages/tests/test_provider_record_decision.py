"""Both graph CLIs use the same hashed decision writer and status resolution."""

from __future__ import annotations

import json
import subprocess

from packages.tests.test_provider_controller_commands import LOOP, SESSION, Controller, ControllerCase


def decide(c: Controller, *extra: str, session: str = SESSION) -> subprocess.CompletedProcess[str]:
    """Run the typed command against the current graph revision."""
    return c.run(
        "record-decision",
        "--session",
        session,
        "--loop-id",
        LOOP,
        "--revision",
        str(c.read()["revision"]),
        "--phase",
        "2.6",
        "--decision",
        "disposition",
        *extra,
    )


class RecordDecisionTests(ControllerCase):
    """Check the local commit and refusal boundary through provider CLIs."""

    def started(self, c: Controller) -> None:
        """Use a fixture graph and prevent access to the operator's Muninn binary."""
        c.env["PATH"] = "/usr/bin:/bin"
        self.assertEqual(c.start().returncode, 0)

    def test_hashed_rows_continue_after_legacy_row(self) -> None:
        """A typed write keeps old data and starts one valid chain."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["decisions_absorbed"] = [{"phase": "2.5", "decision": "prior choice"}]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            result = decide(c, "--chosen", "clean-break")
            self.assertEqual(result.returncode, 3, result.stderr)
            rows = c.read()["decisions_absorbed"]
            self.assertEqual(rows[0], {"phase": "2.5", "decision": "prior choice"})
            self.assertEqual(rows[1]["seq"], 2)
            self.assertEqual(rows[1]["chosen"], "clean-break")
            self.assertEqual(rows[1]["prev_sha256"], "0" * 64)
            self.assertEqual(len(rows[1]["row_sha256"]), 64)
            self.assertEqual(rows[1]["muninn"]["state"], "degraded")
            self.assertEqual(c.read()["chain_started_seq"], 2)

    def test_status_and_hash_commit_together_but_sync_still_blocks(self) -> None:
        """One decision resolves the named status without opening the next wave on failed sync."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["worker_statuses"] = [
                {
                    "seq": 1,
                    "node": "U3[1]",
                    "status": "NEEDS_DECISION",
                    "payload": {"options": ["allow", "deny"]},
                    "decision_pending": True,
                }
            ]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            result = decide(c, "--chosen", "allow", "--worker-status-seq", "1")
            self.assertEqual(result.returncode, 3, result.stderr)
            current = c.read()
            self.assertEqual(current["worker_statuses"][0]["resolved_by_decision"], 1)
            self.assertFalse(current["worker_statuses"][0]["decision_pending"])
            self.assertEqual(current["decisions_absorbed"][0]["worker_status_seq"], 1)
            self.assertEqual(current["decisions_absorbed"][0]["chosen"], "allow")

    def test_refusal_preserves_bytes(self) -> None:
        """Wrong owner, blank answer and unknown status do not modify the graph."""
        for c in self.each():
            self.started(c)
            cases = (
                (decide(c, session="foreign"), "decision_wrong_session"),
                (decide(c, "--chosen", " "), "record_decision_refused_field"),
                (decide(c, "--chosen", "yes", "--worker-status-seq", "9"), "record_decision_refused_status"),
            )
            for result, reason in cases:
                before = c.path.read_bytes()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)["reason_code"], reason)
                self.assertEqual(c.path.read_bytes(), before)
