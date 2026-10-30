"""Retro assembled with source hashes and teardown steps, and a gate that recomputes them (Claude half).

Runs against the hermetic fake `muninn` (temp MUNINN_HOME); nothing here touches the live store. Each rule has a
negative control that removes the one check it proves. The Codex gate half lives in
packages/tests/test_codex_completion.py.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from hooks.scripts.lib import loop_completion  # noqa: E402
from hooks.scripts.lib.graph_executor import transition as claude_transition  # noqa: E402
from hooks.scripts.lib.loop_state_common import LoopState  # noqa: E402
from hooks.scripts.tests.lib import claude_transcript_fixture as fixture  # noqa: E402
from scripts.lib import decision_record as dr  # noqa: E402
from scripts.lib import orders, proof, proof_results, retro, retro_check, teardown_steps  # noqa: E402
from scripts.tests.fake_muninn_case import PROMPT, SESSION, StoreCase  # noqa: E402

REQUIRED = list(teardown_steps.REQUIRED)


class Base(StoreCase):
    """A schema-3 loop owned by s1 in <repo-key dir>/s1/, with the fake store ready."""

    with_store = True

    def setUp(self) -> None:
        """Write progress.json and name the caller session."""
        super().setUp()
        os.environ["CLAUDE_CODE_SESSION_ID"] = SESSION
        self.repo_dir = self.tmp / "repo"
        self.dir = self.repo_dir / SESSION
        self.dir.mkdir(parents=True)
        self.path = self.dir / "progress.json"
        self.put(
            {
                **fixture.state(),
                "session_id": SESSION,
                "loop_id": "L1",
                "created": "2026-10-19T00:00:00+00:00",
                "authorising_prompt_raw": PROMPT,
            }
        )

    def put(self, state: dict[str, Any]) -> None:
        """Replace progress.json."""
        self.path.write_text(json.dumps(state))

    def state(self) -> dict[str, Any]:
        """progress.json as it is on disk."""
        return json.loads(self.path.read_text())  # type: ignore[no-any-return]

    def retro(self) -> dict[str, Any]:
        """retro.json as it is on disk."""
        return json.loads((self.dir / "retro.json").read_text())  # type: ignore[no-any-return]

    def decide(self, text: str = "adopt shape A") -> None:
        """Record one decision through the real writer and the Claude lock."""
        state = self.state()
        out = dr.record(
            self.path,
            SESSION,
            "2.5",
            text,
            expected_loop_id=state["loop_id"],
            expected_revision=state["revision"],
            transition=claude_transition,
        )
        self.assertIn(out["exit_code"], (0, 3), out)

    def dispose(self) -> None:
        """Record the typed no-proof disposition (also the proof_run teardown step)."""
        rc = proof.main(["disposition", str(self.dir), "--none", "--reason-code", "docs_only", "--reason", "docs only"])
        self.assertEqual(rc, 0)

    def tick(self) -> None:
        """Tick the orders for this loop (the orders_ticked teardown step)."""
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                orders.main(["--dir", str(self.repo_dir), "--session", SESSION, "tick", "--loop", SESSION]), 0
            )

    def prepare(self) -> None:
        """Write the exact D4 preparation artifact and its owner/source-bound observation."""
        dr.flush_pending(self.path, SESSION, transition=claude_transition)
        state = self.state()
        source = copy.deepcopy(state)
        for key in ("status", "completion", "completed_marker"):
            source.pop(key, None)
        if isinstance(source.get("loop_stop_counts"), dict):
            source["loop_stop_counts"].pop("complete", None)
        binding = {
            "repo_dir": str(self.dir.parent.resolve()),
            "state_dir": str(self.dir.resolve()),
            "session_id": SESSION,
            "loop_id": "L1",
            "revision": state["revision"],
            "progress_sha256": teardown_steps.sha_json(source),
        }
        prepared: dict[str, Any] = {"schema": 1, "binding": binding, "records": []}
        path = self.dir / f"orders-prepared-{hashlib.sha256(b'L1').hexdigest()}.json"
        path.write_text(json.dumps(prepared))
        row = {
            "step": "orders_prepared",
            "session_id": SESSION,
            "loop_id": "L1",
            "revision": state["revision"],
            "binding": binding,
            "evidence_sha256": teardown_steps.sha_json(prepared),
            "ts": "2026-10-19T00:00:00+00:00",
        }
        with (self.dir / teardown_steps.NAME).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row) + "\n")

    def assemble(self, *extra: str) -> tuple[int, dict[str, Any]]:
        """Run `retro.py assemble` and parse its stdout."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = retro.main(["assemble", str(self.dir), "--session", SESSION, *extra])
        return code, json.loads(out.getvalue())

    def ready(self) -> None:
        """Two decisions, a disposition, a bound preparation and an assembled retro."""
        self.decide()
        self.decide("clean-break")
        self.dispose()
        self.prepare()
        self.assertEqual(self.assemble()[0], 0)

    def gate(self) -> list[str]:
        """The real Claude completion gate against what is on disk now; returns only its Muninn-degrade disclosures."""
        got = loop_completion.validate_completion(LoopState(self.path, SESSION, 1, self.state()), "")
        return [m for m in got if m.startswith("Memory degraded")]

    def ids(self) -> dict[str, str]:
        """The loop identity every chained proof row carries."""
        return {"session_id": SESSION, "loop_id": "L1"}

    def rewrite_retro(self, **changes: Any) -> None:  # noqa: ANN401
        """Edit retro.json in place."""
        (self.dir / "retro.json").write_text(json.dumps({**self.retro(), **changes}))


class Assembly(Base):
    """(a) hashes match and the gate accepts; (g) free text is unhashed; the retro is derived, not written."""

    def test_assembled_retro_is_v3_and_accepted(self) -> None:
        """Hashes recompute, decisions are copied verbatim, K-ids are present, and the gate accepts."""
        self.ready()
        got = self.retro()
        self.assertEqual((got["schema_version"], got["status"], got["loop_id"]), (3, "complete", "L1"))
        self.assertEqual(got["source_hashes"], retro_check.source_hashes(self.state(), self.dir))
        self.assertEqual(got["decisions_absorbed"], self.state()["decisions_absorbed"])
        self.assertTrue(all(r["muninn"]["id"] for r in got["decisions_absorbed"]))
        self.assertEqual(got["envelope"], PROMPT)
        self.assertEqual(self.gate(), [])

    def test_teardown_steps_are_listed_in_order(self) -> None:
        """(b) steps_done lists the recorded steps in order; a missing step is rejected."""
        self.ready()
        self.assertEqual(self.retro()["teardown"]["steps_done"], REQUIRED)
        rows = [json.loads(x) for x in (self.dir / "teardown.jsonl").read_text().splitlines()]
        self.assertEqual({"step", "ts", "session_id", "loop_id", "evidence_sha256"}, set(rows[0]))
        (self.dir / "teardown.jsonl").unlink()
        self.assertEqual(self.assemble()[0], 0)
        with self.assertRaisesRegex(ValueError, r"retro_steps_missing.*missing proof_run, orders_prepared"):
            self.gate()


class SourceHashes(Base):
    """(a)(d)(e) any change to a hashed source after assembly is rejected, naming the field."""

    def test_decision_byte_flip_names_the_field_and_control(self) -> None:
        """(2)(1) A case flip in one decision is named; with the hash recompute dropped an evals edit slips through."""
        self.ready()
        state = self.state()
        state["decisions_absorbed"][0]["decision"] = state["decisions_absorbed"][0]["decision"].replace(
            "adopt", "Adopt"
        )
        self.put(state)
        with self.assertRaisesRegex(ValueError, r"retro_source_mismatch: .*progress\.decisions_absorbed"):
            self.gate()
        self.put({**state, "decisions_absorbed": self.retro()["decisions_absorbed"]})
        (self.dir / "evals.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, r"retro_source_mismatch: evals\.json"):
            self.gate()
        stored = self.retro()["source_hashes"]
        with mock.patch.object(retro_check, "source_hashes", return_value=stored):
            self.assertEqual(self.gate(), [])  # control: without the recompute the edited evals.json is not noticed

    def test_forged_derived_sections_are_rejected_and_control(self) -> None:
        """A retro copying the real source_hashes but misstating evals, proof verdicts or dispositions is refused."""
        self.ready()
        cases: list[tuple[str, dict[str, Any]]] = [
            ("evals", {"result": "GO", "amendments": []}),
            ("proof_results", {"verdicts": {"P1": "satisfied"}, "disposition": ""}),
            ("disposition_record", {"units": {"u": "merged"}, "found": True}),
        ]
        for field, forged in cases:
            honest = self.retro()
            self.rewrite_retro(**{field: forged})
            with self.assertRaisesRegex(ValueError, rf"retro_source_mismatch: retro\.{field} differs"):
                self.gate()
            self.rewrite_retro(**{field: honest[field]})
            self.assertEqual(self.gate(), [])

    def test_teardown_evidence_must_recompute_and_control(self) -> None:
        """A hand-appended row with a made-up evidence hash, in a retro re-hashed to match, is refused per step."""
        self.ready()
        rows = (self.dir / "teardown.jsonl").read_text().splitlines()
        for step in ("proof_run", "orders_prepared", "decisions_flushed", "retro_assembled"):
            changed = teardown_steps.read_rows(self.dir)
            row = next(item for item in changed if item["step"] == step)
            row["evidence_sha256"] = "f" * 64
            (self.dir / teardown_steps.NAME).write_text("\n".join(json.dumps(row) for row in changed) + "\n")
            self.rewrite_retro(source_hashes=retro_check.source_hashes(self.state(), self.dir))
            if step not in ("decisions_flushed", "retro_assembled"):
                self.assertEqual(self.assemble()[0], 0)
            with self.assertRaisesRegex(ValueError, rf"retro_steps_missing: teardown step {step} evidence"):
                self.gate()
            (self.dir / "teardown.jsonl").write_text("\n".join(rows) + "\n")
            self.rewrite_retro(source_hashes=retro_check.source_hashes(self.state(), self.dir))
            self.assertEqual(self.gate(), [])  # control: the honest rows recompute
        prepared_rows = teardown_steps.read_rows(self.dir)
        (self.dir / teardown_steps.NAME).write_text(
            "\n".join(json.dumps(row) for row in prepared_rows if row["step"] != "orders_prepared") + "\n"
        )
        self.assertEqual(self.assemble()[0], 0)
        with self.assertRaisesRegex(ValueError, "retro_steps_missing.*missing orders_prepared"):
            self.gate()

    def test_preparation_artifact_missing_even_with_null_receipt(self) -> None:
        """A null receipt cannot validate a deleted D4 preparation artifact."""
        self.ready()
        prepared = next(self.dir.glob("orders-prepared-*.json"))
        prepared.unlink()
        rows = teardown_steps.read_rows(self.dir)
        next(row for row in rows if row["step"] == "orders_prepared")["evidence_sha256"] = None
        (self.dir / teardown_steps.NAME).write_text("\n".join(json.dumps(row) for row in rows) + "\n")
        self.rewrite_retro(source_hashes=retro_check.source_hashes(self.state(), self.dir))
        with self.assertRaisesRegex(ValueError, "retro_steps_missing: teardown step orders_prepared evidence"):
            self.gate()

    def test_proof_results_edit_after_assembly_is_rejected(self) -> None:
        """(d) Appending a row to proof_results.jsonl after assembly is named."""
        self.ready()
        proof_results.append(
            self.dir / "proof_results.jsonl", kind="disposition", verdict="other", excerpt="later", **self.ids()
        )
        with self.assertRaisesRegex(ValueError, r"retro_source_mismatch: proof_results\.jsonl"):
            self.gate()

    def test_assemble_copies_progress_not_memory(self) -> None:
        """(4) The retro's decisions come from progress.json: a store entry that progress lacks is not copied in."""
        self.decide()
        self.dispose()
        self.prepare()
        self.assertEqual(self.assemble()[0], 0)
        self.assertEqual([r["decision"] for r in self.retro()["decisions_absorbed"]], ["adopt shape A"])
        self.rewrite_retro(decisions_absorbed=[{"phase": "x", "decision": "from memory"}])
        with self.assertRaisesRegex(ValueError, r"retro_source_mismatch.*retro\.decisions_absorbed"):
            self.gate()

    def test_legacy_and_hand_written_retros_are_not_assembled(self) -> None:
        """(c) A hand-written v2 retro, or a v3 without source_hashes, is retro_not_assembled."""
        self.ready()
        for hand in ({"schema_version": 2}, {"schema_version": 3}, {"schema_version": 1}):
            (self.dir / "retro.json").write_text(json.dumps({"session_id": SESSION, "loop_id": "L1", **hand}))
            with self.assertRaisesRegex(ValueError, "retro_not_assembled.*retro.py assemble"):
                self.gate()


class Degrade(Base):
    """(f) A Muninn degrade is disclosed, never blocking."""

    def test_degrade_is_disclosed_and_does_not_block(self) -> None:
        """Muninn absent: assemble exits 3 with the reason, the retro is written, the gate returns the counts."""
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.decide()
            self.dispose()
            self.prepare()
            prepared_state = self.state()
            code, out = self.assemble()
        self.assertEqual(self.state(), prepared_state)
        self.assertEqual((code, out["degraded"]), (3, [{"seq": 1, "reason_code": "muninn_absent"}]))
        messages = self.gate()
        self.assertEqual(len(messages), 1)
        self.assertIn("1 decision(s) not in Muninn (muninn_absent: 1)", messages[0])
        self.assertEqual(self.retro()["memory"]["degraded"]["decision.sync"], {"muninn_absent": 2})
        blocking = mock.patch.object(retro_check, "memory_disclosure", side_effect=retro_check.RetroError("x", "y"))
        with blocking, self.assertRaises(ValueError):  # control: a gate that blocked on a degrade fails this test
            self.gate()


class FullChain(Base):
    """(i) start state, decisions, proof freeze and run, orders record and tick, assemble, gate, restart."""

    def test_full_chain_then_restart(self) -> None:
        """Everything in one temp dir with the fake store, then a fresh process re-checks the same files."""
        state = self.state()
        state["graph"]["nodes"]["U3[1]"]["status"] = "skipped"
        state["graph"]["nodes"]["U3[1]"]["outcome"] = "skipped"
        self.put(state)
        self.decide()
        self.decide("clean-break")
        doc = {"schema_version": 2, **{k: self.state()[k] for k in ("session_id", "loop_id")}}
        doc["proofs"] = [{"id": "P1", "cmd": "echo ok", "expect": {"exit_code": 0, "stdout_contains": ["ok"]}}]
        (self.dir / "proof.json").write_text(json.dumps(doc))
        self.assertEqual(proof.main(["freeze", str(self.dir)]), 0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(proof.main(["run", str(self.dir), "--all"]), 0)
            argv = ["--dir", str(self.repo_dir), "--session", SESSION]
            rec = ["record", "--failure-mode", "skipped tests", "--lesson", "Run the tests.", "--loop", "L1"]
            self.assertEqual(orders.main([*argv, *rec, "--quote", PROMPT]), 0)
            self.prepare()
        self.assertEqual(self.assemble()[0], 0)
        self.assertEqual(
            self.retro()["teardown"]["steps_done"],
            ["proof_run", "decisions_flushed", "orders_prepared", "retro_assembled"],
        )
        self.assertEqual(self.retro()["proof_results"]["verdicts"], {"P1": "satisfied"})
        self.assertEqual(self.gate(), [])
        teardown_steps.record(self.dir, "orders_ticked", SESSION, "L1", "applied-after-completion")
        self.assertEqual(self.gate(), [])
        code = (
            "import json,sys;sys.path.insert(0,sys.argv[1]);from pathlib import Path;"
            "from hooks.scripts.lib.loop_completion import validate_completion;"
            "from hooks.scripts.lib.loop_state_common import LoopState;p=Path(sys.argv[2]);"
            "print(json.dumps(validate_completion(LoopState(p,'s1',1,json.loads(p.read_text())),'')))"
        )
        fresh = subprocess.run(
            [sys.executable, "-c", code, str(REPO), str(self.path)], capture_output=True, text=True, check=False
        )
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertEqual([m for m in json.loads(fresh.stdout) if m.startswith("Memory")], [])
        state = copy.deepcopy(self.state())
        state["decisions_absorbed"][0]["phase"] = "9.9"
        self.put(state)
        again = subprocess.run(
            [sys.executable, "-c", code, str(REPO), str(self.path)], capture_output=True, text=True, check=False
        )
        self.assertEqual(again.returncode, 1)  # control: the restarted process rejects the edited state too
        self.assertIn("retro_source_mismatch", again.stderr)


class TeardownStepsUnit(Base):
    """The append-only record: idempotent, validated, one row per step."""

    def test_record_is_idempotent_and_rejects_unknown_steps(self) -> None:
        """The same evidence twice appends once; a changed one appends again; an unknown step never."""
        self.assertTrue(teardown_steps.record(self.dir, "proof_run", SESSION, None, "a"))
        self.assertFalse(teardown_steps.record(self.dir, "proof_run", SESSION, None, "a"))
        self.assertTrue(teardown_steps.record(self.dir, "proof_run", SESSION, None, "b"))
        self.assertFalse(teardown_steps.record(self.dir, "bogus", SESSION, None, "a"))
        rows = teardown_steps.read_rows(self.dir)
        self.assertEqual(
            [(r["step"], r["evidence_sha256"], r["loop_id"]) for r in rows],
            [("proof_run", "a", "L1"), ("proof_run", "b", "L1")],
        )
        self.assertEqual(teardown_steps.steps_done(rows), ["proof_run"])

    def test_torn_file_is_unreadable_not_ignored(self) -> None:
        """A torn line raises, so the gate reports retro_steps_missing instead of silently skipping it."""
        (self.dir / "teardown.jsonl").write_text('{"step": "proof_run"}\n{torn')
        with self.assertRaisesRegex(ValueError, "teardown_unreadable"):
            teardown_steps.read_rows(self.dir)


if __name__ == "__main__":
    unittest.main()
