"""Preserve completion-time evidence, revision, proof, and Stop-hook boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import graph
from graph_artifacts import validate_evals
from graph_completion import complete, verify_completion
from graph_identity import GraphError

from packages.tests.codex_completion_head_case import assert_changed_head, assert_empty_proof_disposition
from packages.tests.codex_fixture import append, frozen_evals, read_json, spawn, state, transcripts, write_json
from scripts.lib import proof_results as pr
from scripts.lib import retro, retro_check, teardown_steps

IDENTITY = {"session_id": "parent", "loop_id": "loop"}


def assemble_test_retro(state_dir: Path, session: str) -> dict[str, Any]:
    """Build source-bound D4 preparation evidence for this isolated completion fixture."""
    path = state_dir / "progress.json"
    current: dict[str, Any] = read_json(path)
    loop_id = str(current.get("loop_id") or "")
    teardown_steps.record(
        state_dir, "proof_run", session, loop_id, teardown_steps.file_sha(state_dir / "proof_results.jsonl")
    )
    # Repeated fixture refreshes model a new completion attempt while keeping the latest receipt order canonical.
    rows = teardown_steps.read_rows(state_dir)
    rank = {name: index for index, name in enumerate(teardown_steps.REQUIRED)}
    rows.sort(key=lambda row: rank.get(row["step"], len(rank)))
    (state_dir / teardown_steps.NAME).write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    retro.assemble(state_dir, session)  # explicit decision flush must precede preparation
    current = read_json(path)
    source = dict(current)
    if source.get("status") == "complete" and isinstance(source.get("completion"), dict):
        source["revision"] = source["completion"]["revision"]
    for key in ("status", "completion", "completed_marker"):
        source.pop(key, None)
    if isinstance(source.get("loop_stop_counts"), dict):
        source["loop_stop_counts"].pop("complete", None)
    binding = {
        "repo_dir": str(state_dir.parent.resolve()),
        "state_dir": str(state_dir.resolve()),
        "session_id": session,
        "loop_id": loop_id,
        "revision": source["revision"],
        "progress_sha256": teardown_steps.sha_json(source),
    }
    prepared: dict[str, Any] = {"schema": 1, "binding": binding, "records": []}
    prep_path = state_dir / f"orders-prepared-{hashlib.sha256(loop_id.encode()).hexdigest()}.json"
    prep_path.write_text(json.dumps(prepared), encoding="utf-8")
    row = {
        "step": "orders_prepared",
        "session_id": session,
        "loop_id": loop_id,
        "revision": source["revision"],
        "binding": binding,
        "evidence_sha256": teardown_steps.sha_json(prepared),
        "ts": "2026-10-19T00:00:00+00:00",
    }
    with (state_dir / teardown_steps.NAME).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    payload, code = retro.assemble(state_dir, session)
    if code == 2:
        raise AssertionError(payload)
    return read_json(state_dir / "retro.json")


class CompletionTests(unittest.TestCase):
    """Only current native evidence and successful observed proofs permit completion."""

    def setUp(self) -> None:
        """Create a completed worker with independent proof and eval artifacts."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "loops/project/parent/progress.json"
        self.path.parent.mkdir(parents=True)
        write_json(self.path, state())
        self.evals = self.path.with_name("evals.json")
        write_json(self.evals, frozen_evals())
        parent = transcripts(self.directory)
        graph.begin_wave(self.path)
        self.child = spawn(parent, read_json(self.path))
        graph.record_wave(
            self.path,
            json.dumps({"wave_id": "wave-2", "results": {"U3[1]": {"outcome": "done", "evidence": "checked"}}}),
        )
        suite: dict[str, Any] = frozen_evals() | {
            "verification_level": 0,
            "revision": 3,
            "evals": [],
            "amendments": [],
            "result": "VERIFICATION_LEVEL0",
            "grading": {
                "by": "post_evals.py grade-loop",
                "checksum": hashlib.sha256(b"[]\nVERIFICATION_LEVEL0").hexdigest(),
                "amendments_at_grade": 0,
            },
        }
        write_json(self.evals, suite)
        self.proof, self.retro = self.path.with_name("proof.json"), self.path.with_name("retro.json")
        self.document: dict[str, Any] = {
            "schema_version": 2,
            "session_id": "parent",
            "loop_id": "loop",
            "proofs": [{"id": "P1", "cmd": "true", "expect": {"exit_code": 0}}],
        }
        write_json(self.proof, self.document)
        self.results = self.path.with_name(pr.RESULTS_NAME)
        pr.append(self.results, kind="freeze", proof_json_sha256=pr.doc_sha(self.document), **IDENTITY)
        self.proof_result("satisfied")
        assemble_test_retro(self.path.parent, "parent")
        self.transcript = self.path.with_name("proof.jsonl")
        append(self.transcript, {"type": "turn_context", "payload": {"loop_id": "loop"}})
        self.arguments = (self.path, "parent", self.evals, self.proof, self.retro, self.transcript)

    def proof_result(self, verdict: str, cmd: str = "true", **identity: str) -> None:
        """Append one controller run row for proof P1."""
        pr.append(
            self.results,
            kind="run",
            proof_id="P1",
            cmd_sha256=pr.sha(cmd),
            proof_json_sha256=pr.doc_sha(self.document),
            verdict=verdict,
            cwd=str(Path.cwd()),
            head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            **(IDENTITY | identity),
        )

    def test_success_and_revalidation(self) -> None:
        """A completed graph is revalidated against the latest run row."""
        complete(*self.arguments)
        verify_completion(*self.arguments)
        self.proof_result("failed")
        with self.assertRaises(GraphError):
            verify_completion(*self.arguments)

    def test_preparation_binding_is_source_checked(self) -> None:
        """Each D4 binding field must match the owned state and producer source."""
        complete(*self.arguments)
        rows = teardown_steps.read_rows(self.path.parent)
        row = next(item for item in rows if item["step"] == "orders_prepared")
        artifact = self.path.parent / f"orders-prepared-{hashlib.sha256(b'loop').hexdigest()}.json"
        saved = artifact.read_bytes()
        for key, value in {
            "repo_dir": "/foreign/repo",
            "state_dir": "/foreign/state",
            "session_id": "foreign",
            "loop_id": "foreign",
            "revision": row["revision"] + 1,
            "progress_sha256": "0" * 64,
        }.items():
            with self.subTest(binding=key):
                changed = dict(row, binding=row["binding"] | {key: value})
                if key == "revision":
                    changed["revision"] = value
                (self.path.parent / teardown_steps.NAME).write_text(
                    "\n".join(json.dumps(item) for item in [*rows, changed]) + "\n"
                )
                with self.assertRaises(GraphError):
                    verify_completion(*self.arguments)
                (self.path.parent / teardown_steps.NAME).write_text("\n".join(json.dumps(item) for item in rows) + "\n")
                artifact.write_bytes(saved)
                verify_completion(*self.arguments)

    def test_prepared_artifact_digest_is_source_checked(self) -> None:
        """Editing prepared records invalidates the completion evidence digest."""
        complete(*self.arguments)
        artifact = self.path.parent / f"orders-prepared-{hashlib.sha256(b'loop').hexdigest()}.json"
        prepared = json.loads(artifact.read_text())
        prepared["records"].append({"id": "tampered"})
        artifact.write_text(json.dumps(prepared))
        with self.assertRaises(GraphError):
            verify_completion(*self.arguments)

    def test_changed_head_invalidates_codex_completion(self) -> None:
        """Revalidation refuses a proof that passed before this worktree advanced."""
        assert_changed_head(self, assemble_test_retro)

    def test_unsatisfied_foreign_or_stale_rows_cannot_pass(self) -> None:
        """Failed, mismatched, foreign-loop, wrong-cmd and status-only proofs never complete the graph."""
        for verdict, cmd, identity in (
            ("failed", "true", {}),
            ("expect_mismatch", "true", {}),
            ("timeout", "true", {}),
            ("satisfied", "other", {}),
            ("satisfied", "true", {"loop_id": "foreign"}),
        ):
            self.proof_result(verdict, cmd, **identity)
            before = self.path.read_bytes()
            with self.assertRaisesRegex(GraphError, r"P1\(proof_"):
                complete(*self.arguments)
            self.assertEqual(before, self.path.read_bytes())
            self.results.unlink()
            pr.append(self.results, kind="freeze", proof_json_sha256=pr.doc_sha(self.document), **IDENTITY)
        self.document["proofs"][0]["status"] = "pass"
        write_json(self.proof, self.document)
        with self.assertRaisesRegex(GraphError, r"P1\(proof_stale_cmd\)"):
            complete(*self.arguments)

    def test_no_proof_needs_a_typed_disposition(self) -> None:
        """With no proof.json a bare none is rejected and none-with-reason or the typed form completes."""
        self.proof.unlink()
        assemble_test_retro(self.path.parent, "parent")
        current = read_json(self.path)
        rejected: tuple[object, ...] = (None, "none", "none: ")
        for disposition in rejected:
            write_json(self.path, current | {"proof_disposition": disposition})
            assemble_test_retro(self.path.parent, "parent")
            with self.assertRaisesRegex(GraphError, "proof_disposition_no_reason"):
                complete(*self.arguments)
        typed = {"kind": "none", "reason_code": "docs_only", "reason": "documentation only"}
        accepted: tuple[object, ...] = ("none: no executable surface", typed)
        for disposition in accepted:
            write_json(self.path, current | {"proof_disposition": disposition})
            assemble_test_retro(self.path.parent, "parent")
            complete(*self.arguments)
            write_json(self.path, current)

    def decide(self, text: str = "adopt shape A", muninn: dict[str, Any] | None = None) -> None:
        """Put one hashed decision row into progress.json, then re-assemble the retro over it."""
        from scripts.lib import decision_record as dr

        added = dr.add_decision(read_json(self.path), "parent", "2.5", text)["state"]
        added["decisions_absorbed"][-1]["muninn"] = muninn or {"state": "written", "id": "K1", "reason_code": "ok"}
        write_json(self.path, added)
        assemble_test_retro(self.path.parent, "parent")

    def test_retro_gate_recomputes_hashes_on_the_codex_gate(self) -> None:
        """(a)(b)(c)(d)(e) The Codex gate refuses a hand-written, edited, step-less or chain-broken retro."""
        self.decide()
        complete(*self.arguments)
        verify_completion(*self.arguments)
        original = read_json(self.path)
        edited = [dict(original["decisions_absorbed"][0], decision="Adopt shape A")]
        write_json(self.path, original | {"decisions_absorbed": edited})
        with self.assertRaisesRegex(GraphError, r"retro_source_mismatch: .*progress\.decisions_absorbed"):
            verify_completion(*self.arguments)
        write_json(self.path, original)
        write_json(self.retro, read_json(self.retro) | {"schema_version": 2})
        with self.assertRaisesRegex(GraphError, "retro_not_assembled"):
            verify_completion(*self.arguments)
        assemble_test_retro(self.path.parent, "parent")
        pr.append(self.results, kind="disposition", verdict="other", excerpt="later", **IDENTITY)
        with self.assertRaisesRegex(GraphError, r"retro_source_mismatch: proof_results\.jsonl"):
            verify_completion(*self.arguments)
        assemble_test_retro(self.path.parent, "parent")
        verify_completion(*self.arguments)
        teardown = self.path.with_name("teardown.jsonl")
        kept = [x for x in teardown.read_text().splitlines() if '"step": "orders_prepared"' not in x]
        teardown.write_text("\n".join(kept) + "\n")
        retro.assemble(self.path.parent, "parent")
        with self.assertRaisesRegex(GraphError, "retro_steps_missing"):
            verify_completion(*self.arguments)

    def test_retro_in_a_scratch_directory_is_refused_and_control(self) -> None:
        """A retro from another directory (decoy sources) is refused; the same retro beside the real files passes."""
        self.decide()
        scratch = self.directory / "scratch"
        scratch.mkdir()
        real = self.arguments
        decoy = scratch / "retro.json"
        decoy.write_text(self.retro.read_text())
        with self.assertRaisesRegex(GraphError, "one state directory"):
            complete(real[0], real[1], real[2], real[3], decoy, real[5])
        complete(*real)  # control: the genuine layout is accepted
        verify_completion(*real)

    def test_broken_decision_chain_is_refused_on_the_codex_gate(self) -> None:
        """(e) A decision edited before re-assembly still fails verify_chain."""
        self.decide()
        self.decide("clean-break")
        original = read_json(self.path)
        rows = original["decisions_absorbed"]
        write_json(self.path, original | {"decisions_absorbed": [rows[0], dict(rows[1], decision="edited")]})
        assemble_test_retro(self.path.parent, "parent")
        with self.assertRaisesRegex(GraphError, r"retro_decisions_chain_broken.*seq 2"):
            complete(*self.arguments)

    def test_muninn_degrade_is_disclosed_not_blocking_and_gate_wiring_is_enforcing(self) -> None:
        """(f)(6) A degraded decision is disclosed in the result; with the gate unwired a tampered retro would pass."""
        self.decide(muninn={"state": "degraded", "id": None, "reason_code": "muninn_absent"})
        done = complete(*self.arguments)
        self.assertEqual(len(done["disclosures"]), 1)
        self.assertIn("Memory degraded: 1 decision(s) not in Muninn", done["disclosures"][0])
        write_json(self.retro, read_json(self.retro) | {"schema_version": 2})
        with self.assertRaisesRegex(GraphError, "retro_not_assembled"):
            verify_completion(*self.arguments)
        with patch.object(retro_check, "check", return_value=[]):
            verify_completion(*self.arguments)  # control: reverting the wiring lets the hand-written retro through

    def test_empty_proof_file_uses_a_valid_disposition(self) -> None:
        """An owned empty proof document follows the same disposition rule as Claude."""
        assert_empty_proof_disposition(self, assemble_test_retro)

    def test_eval_stamp_revision_and_identity(self) -> None:
        """Bind completion to the current suite, checksum, amendments, and loop."""
        suite = read_json(self.evals)
        replacements: tuple[dict[str, Any], ...] = (
            {"revision": 1},
            {"session_id": "foreign"},
            {"loop_id": "foreign"},
            {"grading": {}},
            {"amendments": ["new"]},
            {"result": "NO-GO"},
            {"grading": suite["grading"] | {"checksum": "fake"}},
        )
        for replacement in replacements:
            write_json(self.evals, suite | replacement)
            with self.assertRaises(GraphError):
                complete(*self.arguments)
        write_json(self.evals, frozen_evals())
        validate_evals(read_json(self.path), None, self.evals)
        with self.assertRaises(GraphError):
            complete(*self.arguments)

    def test_work_units_and_proof_ownership(self) -> None:
        """A terminal graph cannot hide unfinished units or foreign proof ownership."""
        current = read_json(self.path)
        write_json(self.path, current | {"work_units": {"unmapped": {"status": "pending"}}})
        with self.assertRaises(GraphError):
            complete(*self.arguments)
        write_json(self.path, current)
        proof = read_json(self.proof)
        replacements: tuple[dict[str, Any], ...] = (
            {"loop_id": "foreign"},
            {"proofs": []},
            {"proofs": [{"id": "", "cmd": "true"}]},
        )
        for replacement in replacements:
            write_json(self.proof, proof | replacement)
            with self.assertRaises(GraphError):
                complete(*self.arguments)

    def test_completed_native_stop(self) -> None:
        """Stop allows valid completion, rejects later failure, and retains recursion guard."""
        complete(*self.arguments)
        package = Path(__file__).resolve().parents[1] / "codex"
        environment = os.environ | {
            "HOME": str(self.directory),
            "PLUGIN_ROOT": str(package),
            "PLUGIN_DATA": str(self.directory / "data"),
            "CODERAILS_AGENTIC_LOOP_DIR": str(self.directory / "loops"),
        }
        payload: dict[str, Any] = {
            "session_id": "parent",
            "cwd": str(self.directory),
            "hook_event_name": "Stop",
            "last_assistant_message": "done",
            "transcript_path": str(self.transcript),
        }
        for failed in (False, True):
            if failed:
                self.proof_result("failed")
            result = subprocess.run(
                [sys.executable, str(package / "hooks/scripts/graph_completion_guard.py")],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                env=environment,
                check=True,
            )
            output: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
            self.assertEqual(output.get("decision") == "block", failed)
        payload["stop_hook_active"] = True
        result = subprocess.run(
            [sys.executable, str(package / "hooks/scripts/graph_completion_guard.py")],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=environment,
            check=True,
        )
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
