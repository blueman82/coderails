"""handoff_derive: a read-only skeleton from recorded state, with every degrade named (never silently skipped)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from hooks.scripts.lib.graph_executor import transition as claude_transition  # noqa: E402
from hooks.scripts.tests.lib import claude_transcript_fixture as fixture  # noqa: E402
from scripts.lib import decision_record as dr  # noqa: E402
from scripts.lib import handoff_derive, orders, proof_results  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT, SESSION, StoreCase  # noqa: E402


class Derive(StoreCase):
    """A fixture loop owned by s1 with two recorded decisions."""

    with_store = True

    def setUp(self) -> None:
        """Write progress.json under <repo-key dir>/s1/ and record the decisions."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.repo_dir = self.tmp / "repo"
        self.path = self.repo_dir / SESSION / "progress.json"
        self.path.parent.mkdir(parents=True)
        state: dict[str, Any] = {
            **fixture.state(),
            "session_id": SESSION,
            "loop_id": "L1",
            "created": "2026-10-19T00:00:00+00:00",
            "authorising_prompt_raw": PROMPT,
        }
        state["graph"]["nodes"]["U3[1]"]["status"] = "skipped"
        state["graph"]["nodes"]["U3[1]"]["outcome"] = "skipped"
        self.path.write_text(json.dumps(state))
        for text in ("adopt shape A", "clean-break"):
            current = json.loads(self.path.read_text())
            dr.record(
                self.path,
                SESSION,
                "2.5",
                text,
                expected_loop_id=current["loop_id"],
                expected_revision=current["revision"],
                transition=claude_transition,
            )

    def derive(self) -> tuple[dict[str, Any], int]:
        """Run the CLI path and parse its JSON."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = handoff_derive.main([str(self.path), "--session", SESSION])
        return json.loads(out.getvalue()), code

    def test_decisions_carry_k_ids_and_cites(self) -> None:
        """(h) Each progress decision is printed with its K-id and the cite Muninn holds; nothing degraded, exit 0."""
        got, code = self.derive()
        self.assertEqual((code, got["degraded"]), (0, []))
        self.assertEqual([d["text"] for d in got["decisions"]], ["adopt shape A", "clean-break"])
        self.assertTrue(all(d["id"] and d["id"].startswith("K") and d["cite"] for d in got["decisions"]))
        self.assertEqual({d["source"] for d in got["decisions"]}, {"progress"})
        self.assertEqual(got["goal"], PROMPT)

    def test_skipped_graph_node_is_not_reported_done(self) -> None:
        """The graph summary includes skipped nodes, but the handoff must not call them done."""
        got, code = self.derive()
        self.assertEqual(code, 0)
        self.assertNotIn("U3[1]", got["done"])
        self.assertIn("skipped", " ".join(got["next_steps"] + got["open_questions"]).lower())

    def test_broken_decision_chain_is_degraded_without_a_false_cite(self) -> None:
        """An edited progress decision cannot inherit its old Muninn citation."""
        state = json.loads(self.path.read_text())
        state["decisions_absorbed"][0]["decision"] = "forged choice"
        self.path.write_text(json.dumps(state))
        got, code = self.derive()
        self.assertEqual(code, 3)
        self.assertIn({"source": "decisions", "reason": "decision_invalid_chain"}, got["degraded"])
        self.assertFalse(any(d["source"] == "progress" for d in got["decisions"]))

    def test_muninn_only_decision_is_added(self) -> None:
        """A store decision that progress.json does not name is still listed, marked as from muninn."""
        state = json.loads(self.path.read_text())
        state["decisions_absorbed"] = state["decisions_absorbed"][:1]
        self.path.write_text(json.dumps(state))
        got, _ = self.derive()
        self.assertEqual([(d["source"], d["text"]) for d in got["decisions"]][-1][0], "muninn")
        self.assertEqual(len(got["decisions"]), 2)

    def test_muninn_absent_degrades_loudly_and_keeps_progress_decisions(self) -> None:
        """(h) Muninn absent: the progress-derived decisions print, degraded names muninn_absent, exit 3."""
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            got, code = self.derive()
        self.assertEqual(code, 3)
        self.assertEqual([d["reason"] for d in got["degraded"] if d["source"] == "decisions"], ["muninn_absent"])
        self.assertEqual([d["text"] for d in got["decisions"]], ["adopt shape A", "clean-break"])
        self.assertTrue(all(d["id"] for d in got["decisions"]))  # the K-ids recorded earlier stay printed
        self.assertTrue(all(d["cite"] is None for d in got["decisions"]))  # but without the store the cite is unknown

    def test_recorded_degraded_decision_is_disclosed_with_reachable_store(self) -> None:
        """A successful list cannot make an uncited progress decision appear sound."""
        state = json.loads(self.path.read_text())
        state["decisions_absorbed"][0]["muninn"] = {
            "state": "degraded",
            "id": None,
            "reason_code": "muninn_absent",
        }
        self.path.write_text(json.dumps(state))
        got, code = self.derive()
        self.assertEqual(code, 3)
        self.assertIn({"source": "decisions", "reason": "muninn_absent"}, got["degraded"])
        self.assertIsNone(got["decisions"][0]["cite"])

    def test_unexecuted_and_failed_proofs_stay_out_of_done(self) -> None:
        """A frozen proof without a satisfied run stays a next step."""
        document = {
            "schema_version": 2,
            "session_id": SESSION,
            "loop_id": "L1",
            "proofs": [{"id": "P1", "cmd": "false"}, {"id": "P2", "cmd": "true"}],
        }
        self.path.with_name("proof.json").write_text(json.dumps(document))
        got, code = self.derive()
        self.assertEqual(code, 0)
        self.assertIn("proof P1: unexecuted", got["next_steps"])
        self.assertIn("proof P2: unexecuted", got["next_steps"])
        digest = proof_results.doc_sha(document)
        result_path = self.path.with_name("proof_results.jsonl")
        proof_results.append(result_path, kind="freeze", proof_json_sha256=digest, session_id=SESSION, loop_id="L1")
        proof_results.append(
            result_path,
            kind="run",
            proof_id="P1",
            cmd_sha256=proof_results.sha("false"),
            proof_json_sha256=digest,
            verdict="failed",
            cwd=str(self.repo_dir),
            head_sha="0" * 40,
            session_id=SESSION,
            loop_id="L1",
        )
        got, code = self.derive()
        self.assertEqual(code, 0)
        self.assertIn("proof P1: failed", got["next_steps"])
        self.assertIn("proof P2: unexecuted", got["next_steps"])
        self.assertFalse(any("proof P1" in line for line in got["done"]))
        proof_results.append(
            result_path,
            kind="run",
            proof_id="P1",
            cmd_sha256=proof_results.sha("false"),
            proof_json_sha256=digest,
            verdict="satisfied",
            cwd=str(self.repo_dir),
            head_sha="0" * 40,
            session_id="foreign",
            loop_id="other",
        )
        got, code = self.derive()
        self.assertEqual(code, 0)
        self.assertIn("proof P1: satisfied", got["recorded_proof_results"])
        self.assertIn("verify proof P1: satisfied", got["next_steps"])
        self.assertFalse(any("proof P1" in line for line in got["done"]))

    def test_backend_off_is_an_explicit_opt_out(self) -> None:
        """memory.backend off lists its reason but exits 0."""
        with mock.patch.object(ma, "backend", return_value="off"):
            got, code = self.derive()
        self.assertEqual((code, [d["reason"] for d in got["degraded"]]), (0, ["memory_backend_off"]))

    def test_lessons_and_proofs_are_derived(self) -> None:
        """A staged order stays out of active lessons; a missing graph is graph_unavailable, not silence."""
        with contextlib.redirect_stdout(io.StringIO()):
            argv = ["--dir", str(self.repo_dir), "--session", SESSION]
            rec = ["record", "--failure-mode", "skipped tests", "--lesson", "Run the tests.", "--loop", "L1"]
            self.assertEqual(orders.main([*argv, *rec, "--quote", PROMPT]), 0)
        got, code = self.derive()
        self.assertEqual(got["lessons"], [])
        self.assertEqual(code, 0, got["degraded"])
        with mock.patch.object(handoff_derive, "GRAPH", Path("/nonexistent/graph.py")):
            got, code = self.derive()
        self.assertEqual(
            (code, sorted(d["reason"] for d in got["degraded"])), (3, ["graph_unavailable", "graph_unavailable"])
        )

    def test_both_handoff_skills_make_it_step_zero_and_require_stating_degraded(self) -> None:
        """Each provider's handoff skill runs handoff_derive.py first and tells the model to state degraded[]."""
        for rel in ("skills/handoff/SKILL.md", "packages/codex/skills/handoff/SKILL.md"):
            text = (REPO / rel).read_text()
            step0 = text.split("### Step 0", 1)[1].split("### Step 1", 1)[0]
            self.assertIn("scripts/lib/handoff_derive.py", step0, rel)
            self.assertIn("State `degraded[]` to the user", step0, rel)

    def test_unreadable_state_is_refused_and_nothing_is_written(self) -> None:
        """A missing progress.json exits 2 with a reason code."""
        self.path.unlink()
        got, code = self.derive()
        self.assertEqual((code, got["reason_code"]), (2, "handoff_state_unreadable"))

    def test_foreign_session_is_refused_before_sources_are_joined(self) -> None:
        """The caller cannot mix this progress source with another session's Muninn records."""
        got, code = handoff_derive.derive(self.path, "another-session")
        self.assertEqual((code, got), (2, {"reason_code": "handoff_wrong_session"}))

    def test_broken_proof_chain_is_degraded_not_done(self) -> None:
        """A corrupt proof log cannot be presented as completed work with a success exit."""
        self.path.with_name("proof_results.jsonl").write_text("{broken\n")
        got, code = self.derive()
        self.assertEqual(code, 3)
        self.assertIn({"source": "proofs", "reason": "proof_chain_broken"}, got["degraded"])
        self.assertFalse(any("proof_chain_broken" in line for line in got["done"]))


if __name__ == "__main__":
    unittest.main()
