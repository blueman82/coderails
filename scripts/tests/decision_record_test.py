"""Typed hash-chained decisions: local-first append, Muninn sync, degrade paths, chain tamper-evidence, mirrors.

Runs against the hermetic fake `muninn` (temp MUNINN_HOME) through BOTH providers' real lock functions. Each rule has a
negative control that mutates the one thing it proves. Nothing here touches the live Muninn store.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
CODEX_SCRIPTS = REPO / "packages/codex/skills/agentic-loop/scripts"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(CODEX_SCRIPTS))

graph_io: Any = importlib.import_module("graph_io")
worker_status: Any = importlib.import_module("worker_status")
decision_pending: Any = importlib.import_module("graph_vocab").decision_pending

from hooks.scripts.lib.graph_executor import transition as claude_transition  # noqa: E402
from hooks.scripts.tests.lib import claude_transcript_fixture as fixture  # noqa: E402
from scripts.lib import decision_record as dr  # noqa: E402
from scripts.lib import memory_adapter as ma  # noqa: E402
from scripts.tests.fake_muninn_case import LATER, PROMPT, SESSION, StoreCase  # noqa: E402


def codex_transition(path: Path, fn: Any) -> dict[str, Any]:  # noqa: ANN401
    """The Codex lock wrapper lane A uses: graph_io locked/load/write around one transform."""
    with graph_io.locked(path):
        new = fn(graph_io.load(path))
        graph_io.write(path, new)
        return new  # type: ignore[no-any-return]


PROVIDERS = (("claude", claude_transition), ("codex", codex_transition))


class Base(StoreCase):
    """A schema-3 loop state owned by session s1 on disk, with the fake store ready."""

    with_store = True

    def setUp(self) -> None:
        """Write the state fixture and name the caller session for bare-quote cites."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.path = self.tmp / "progress.json"
        self.put({**fixture.state(), "session_id": SESSION, "loop_id": "L1", "authorising_prompt_raw": PROMPT})

    def put(self, state: dict[str, Any]) -> None:
        """Replace the state file."""
        self.path.write_text(json.dumps(state))

    def state(self) -> dict[str, Any]:
        """The state file as it is on disk."""
        return json.loads(self.path.read_text())  # type: ignore[no-any-return]

    def decisions(self) -> list[dict[str, Any]]:
        """The decisions_absorbed rows on disk."""
        return self.state().get("decisions_absorbed", [])  # type: ignore[no-any-return]

    def trace(self) -> list[dict[str, Any]]:
        """Trace rows of session s1."""
        path = self.tmp / "loops" / SESSION / "trace.jsonl"
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def rec(
        self,
        tr: dr.Transition = claude_transition,
        phase: str = "2.5",
        text: str = "adopt shape A",
        **kw: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """Call record with the given provider lock."""
        state = self.state()
        return dr.record(
            self.path,
            SESSION,
            phase,
            text,
            expected_loop_id=state["loop_id"],
            expected_revision=state["revision"],
            transition=tr,
            **kw,
        )


class MuninnSync(Base):
    """(b) written, (c) absent, (d) approval prompt then retry, (e) off, and local-first under a crash."""

    def test_written_matches_store_and_survives_restart(self) -> None:
        """The row's muninn.id is the K-id in the store, citing the authorising prompt; a fresh process sees it."""
        out = self.rec()
        got = self.listed()
        self.assertEqual((out["exit_code"], out["muninn"]["state"]), (0, "written"))
        self.assertEqual([r.id for r in got], [out["muninn"]["id"]])
        self.assertEqual((got[0].quote, got[0].type, got[0].confidence), (PROMPT, "decision", "inferred"))
        self.assertIn("run-l1", got[0].tags)
        rc, listing = self.muninn("know", "list", "--scope-loop", "L1", extra_env={"CLAUDE_CODE_SESSION_ID": SESSION})
        entry = listing["entries"][0]
        self.assertEqual((rc, entry["id"], entry["cites"][0]["quote"]), (0, out["muninn"]["id"], PROMPT))

    def test_absent_muninn_is_loud_local_row_kept_no_markdown(self) -> None:
        """(c) degraded/muninn_absent, exit 3, a trace row, the local row exists, no .md file anywhere new."""

        def md() -> set[Path]:
            return set(self.tmp.rglob("*.md")) | set((REPO / "docs").glob("*.md"))

        before = md()
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            out = self.rec()
        got = (out["exit_code"], out["muninn"]["state"], out["muninn"]["reason_code"])
        self.assertEqual(got, (3, "degraded", "muninn_absent"))
        self.assertEqual(self.decisions()[0]["muninn"]["reason_code"], "muninn_absent")
        sync = [r for r in self.trace() if r["command"] == "decision.sync"]
        self.assertEqual([(r["outcome"], r["reason_code"]) for r in sync], [("degraded", "muninn_absent")])
        self.assertEqual(md(), before)

    def test_approval_prompt_degrades_then_flush_writes_the_same_seq(self) -> None:
        """(d) 'yes' degrades visibly; a substantive cite_quote at flush patches the SAME seq to written."""
        self.put({**self.state(), "authorising_prompt_raw": "yes"})
        out = self.rec()
        self.assertEqual((out["exit_code"], out["muninn"]["state"]), (3, "degraded"))
        self.assertIn(out["muninn"]["reason_code"], ("refused_approval_needs_reply", "cite_too_short"))
        stuck = dr.flush_pending(self.path, SESSION, transition=claude_transition)
        self.assertEqual(stuck["exit_code"], 3)  # control: no new cite, still degraded
        done = dr.flush_pending(self.path, SESSION, transition=claude_transition, cite_quote=LATER)
        self.assertEqual((done["exit_code"], [x["seq"] for x in done["synced"]]), (0, [1]))
        row = self.decisions()[0]
        self.assertEqual((row["seq"], row["muninn"]["state"]), (1, "written"))
        self.assertEqual(dr.verify_chain(self.decisions()), [])  # patching muninn never breaks the hash
        again = dr.flush_pending(self.path, SESSION, transition=claude_transition)
        self.assertEqual(again["synced"], [])  # written rows are not retried

    def test_flush_refuses_a_foreign_session(self) -> None:
        """A session that does not own the state cannot sync or mark its rows; nothing is written."""
        with mock.patch.object(ma, "backend", return_value="off"):
            self.rec()
        self.put({**self.state(), "decisions_absorbed": [{**self.decisions()[0], "muninn": {"state": "pending"}}]})
        before = self.state()
        out = dr.flush_pending(self.path, "other", transition=claude_transition)
        self.assertEqual((out["exit_code"], out["reason_code"], out["synced"]), (2, "decision_wrong_session", []))
        self.assertEqual(self.state()["decisions_absorbed"], before["decisions_absorbed"])
        self.assertEqual(self.listed(), [])

    def test_flush_skips_legacy_rows_and_still_syncs_hashed_ones(self) -> None:
        """A hand-written string or seq-less dict in decisions_absorbed does not crash the teardown flush."""
        with mock.patch.object(ma, "backend", return_value="off"):
            self.rec()
        hashed = {**self.decisions()[0], "seq": 3, "muninn": {"state": "pending"}}
        hashed["row_sha256"] = dr.row_digest(hashed)
        rows = [
            "legacy string",
            {"phase": "-1", "decision": "legacy dict"},
            hashed,
        ]
        self.put({**self.state(), "decisions_absorbed": rows, "chain_started_seq": 3})
        out = dr.flush_pending(self.path, SESSION, transition=claude_transition)
        self.assertEqual([x["seq"] for x in out["synced"]], [3])
        self.assertEqual(self.decisions()[:2], rows[:2])

    def test_quote_must_come_from_a_user_prompt(self) -> None:
        """(6) an authorising prompt that is not in the session transcript cannot be cited: refused, row kept."""
        self.put({**self.state(), "authorising_prompt_raw": "Words the owner never typed anywhere in this session."})
        out = self.rec()
        self.assertEqual((out["exit_code"], out["muninn"]["reason_code"]), (3, "cite_not_user"))
        self.assertEqual(len(self.decisions()), 1)
        self.assertEqual(self.listed(), [])

    def test_backend_off_is_disabled_exit_0(self) -> None:
        """(e) memory.backend off: disabled, exit 0, traced memory_backend_off."""
        with mock.patch.object(ma, "backend", return_value="off"):
            out = self.rec()
        self.assertEqual((out["exit_code"], out["muninn"]["state"]), (0, "disabled"))
        sync = [r for r in self.trace() if r["command"] == "decision.sync"]
        self.assertEqual([(r["outcome"], r["reason_code"]) for r in sync], [("disabled", "memory_backend_off")])
        self.assertEqual(len(self.decisions()), 1)

    def test_local_row_survives_a_crashing_muninn_call(self) -> None:
        """Local-first: with the Muninn call raising, the row is on disk and degraded (a Muninn-first design fails)."""
        with mock.patch.object(dr, "sync_row", side_effect=RuntimeError("boom")):
            out = self.rec()
        self.assertEqual((out["recorded"], out["exit_code"], out["muninn"]["reason_code"]), (True, 3, "muninn_error"))
        self.assertEqual(out["muninn"]["state"], "unknown")
        self.assertEqual(self.decisions()[0]["phase"], "2.5")

    def test_codex_lock_function_syncs_too(self) -> None:
        """The Codex shim path writes Muninn and patches the row exactly like Claude's."""
        out = self.rec(codex_transition)
        self.assertEqual(self.decisions()[0]["muninn"]["id"], out["muninn"]["id"])

    def test_pick_quote(self) -> None:
        """First qualifying line, else sentence, else a 300 char prefix; shorter than 12 stays short."""
        self.assertEqual(dr.pick_quote("ok\nPlease ship the adapter today.\nthanks"), "Please ship the adapter today.")
        self.assertEqual(dr.pick_quote("ok. Then do the real work now. " + "z" * 320), "Then do the real work now.")
        self.assertEqual(len(dr.pick_quote("x" * 400)), 300)
        self.assertEqual(dr.pick_quote("yes"), "yes")


class ChainTamper(Base):
    """verify_chain names an edit, a gap, a swap and a hand-appended row (each is its own negative control)."""

    def chain(self) -> list[dict[str, Any]]:
        """Three recorded rows (Muninn off so this stays a pure chain test)."""
        with mock.patch.object(ma, "backend", return_value="off"):
            for i in (1, 2, 3):
                self.rec(phase=str(i), text=f"decision {i}")
        return self.decisions()

    def test_clean_chain(self) -> None:
        """(g) three untouched rows verify."""
        self.assertEqual(dr.verify_chain(self.chain()), [])

    def test_record_refuses_to_extend_a_tampered_chain(self) -> None:
        """A pre-existing bad digest must stop the writer before it appends another row."""
        rows = self.chain()
        rows[1]["decision"] = "tampered"
        self.put({**self.state(), "decisions_absorbed": rows})
        with mock.patch.object(ma, "backend", return_value="off"):
            out = self.rec(phase="4", text="later")
        self.assertEqual((out["recorded"], out["reason_code"], out["exit_code"]), (False, "decision_invalid_chain", 2))
        self.assertEqual(len(self.decisions()), 3)

    def test_malformed_decision_list_is_not_replaced(self) -> None:
        """A scalar decision field must survive a refused record and flush."""
        self.put({**self.state(), "decisions_absorbed": "damaged"})
        before = self.path.read_bytes()
        for _, transition in PROVIDERS:
            out = self.rec(tr=transition)
            self.assertEqual(
                (out["recorded"], out["reason_code"], out["exit_code"]), (False, "decision_invalid_chain", 2)
            )
            self.assertEqual(self.path.read_bytes(), before)
            out = dr.flush_pending(self.path, SESSION, transition=transition)
            self.assertEqual((out["synced"], out["reason_code"], out["exit_code"]), ([], "decision_invalid_chain", 2))
            self.assertEqual(self.path.read_bytes(), before)

    def test_flush_refuses_to_sync_a_tampered_chain(self) -> None:
        """Teardown must not turn a tampered pending row into a Muninn write."""
        rows = self.chain()
        rows[1]["decision"] = "tampered"
        rows[1]["muninn"] = {"state": "pending"}
        self.put({**self.state(), "decisions_absorbed": rows})
        out = dr.flush_pending(self.path, SESSION, transition=claude_transition)
        self.assertEqual((out["synced"], out["reason_code"], out["exit_code"]), ([], "decision_invalid_chain", 2))
        self.assertEqual(self.listed(), [])

    def test_edited_middle_row_is_named(self) -> None:
        """(1) editing row 2's text names seq 2 and only seq 2."""
        rows = self.chain()
        rows[1]["decision"] = "decision 2 (edited)"
        self.assertEqual([(o["seq"], o["reason"]) for o in dr.verify_chain(rows)], [(2, "bad_hash")])

    def test_deleted_row_and_swapped_rows_are_detected(self) -> None:
        """(2) a gap and a reorder are both reported."""
        rows = self.chain()
        self.assertNotEqual(dr.verify_chain([rows[0], rows[2]]), [])
        self.assertNotEqual(dr.verify_chain([rows[1], rows[0], rows[2]]), [])
        self.assertNotEqual(dr.verify_chain([rows[0], rows[2], rows[1]]), [])

    def test_hand_appended_row_after_hashed_rows_is_flagged(self) -> None:
        """(4) {phase, decision} with no hash after the chain began is an offender; legacy rows before it are not."""
        rows = self.chain()
        hand = [*rows, {"phase": "6", "decision": "by hand"}]
        self.assertEqual([o["reason"] for o in dr.verify_chain(hand)], ["unhashed_row"])
        self.assertEqual(dr.verify_chain([{"phase": "-1", "decision": "legacy"}]), [])

    def test_stripping_every_hash_is_caught_with_the_state_marker(self) -> None:
        """Unhashed rows at or after chain_started_seq are offenders; control: without the marker the list passes."""
        rows = self.chain()
        marker = self.state()["chain_started_seq"]
        stripped = [{k: v for k, v in r.items() if k != "row_sha256"} | {"decision": "forged"} for r in rows]
        self.assertEqual(marker, 1)
        self.assertEqual(dr.verify_chain(stripped), [])  # the hole the marker closes
        self.assertEqual([o["seq"] for o in dr.verify_chain(stripped, marker)], [1, 2, 3])
        self.assertEqual(dr.verify_chain(rows, marker), [])

    def test_muninn_field_is_outside_the_hash(self) -> None:
        """Documented boundary: forging muninn.state leaves the chain clean (and flush will not retry it)."""
        rows = self.chain()
        rows[0]["muninn"] = {"state": "written", "id": "K-fake"}
        self.assertEqual(dr.verify_chain(rows), [])

    def test_recomputed_hash_of_an_edited_row_breaks_the_next_link(self) -> None:
        """An editor who recomputes row 2's hash still breaks row 3's prev link (the chain's point)."""
        rows = self.chain()
        rows[1]["decision"] = "rewritten"
        rows[1]["row_sha256"] = dr.row_digest(rows[1])
        self.assertEqual([o["seq"] for o in dr.verify_chain(rows)], [3])


class MirrorAndSize(unittest.TestCase):
    """(h) the Codex copies are byte-identical and the module stays small."""

    def test_mirror_and_size(self) -> None:
        """decision_record.py and memory_reasons.py are byte copies; decision_record.py is under 400 lines."""
        for rel in ("scripts/lib/decision_record.py", "scripts/lib/memory_reasons.py"):
            self.assertEqual((REPO / rel).read_bytes(), (REPO / "packages/codex" / rel).read_bytes(), rel)
        self.assertLess(len((REPO / "scripts/lib/decision_record.py").read_text().splitlines()), 400)

    def test_every_decision_reason_is_documented(self) -> None:
        """Each refusal code the module emits is a memory_reasons key and is named in the RUNBOOK."""
        from scripts.lib import memory_reasons

        runbook = (REPO / "docs/RUNBOOK.md").read_text()
        for code in (f"decision_{x}" for x in (*dr.REFUSALS, "state_error", "sync_unknown")):
            self.assertIn(code, memory_reasons.REASONS)
            self.assertIn(f"`{code}`", runbook)


if __name__ == "__main__":
    unittest.main()
