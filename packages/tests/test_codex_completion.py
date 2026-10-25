"""Preserve completion-time evidence, revision, proof, and Stop-hook boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
from graph_artifacts import validate_completion_evidence, validate_evals
from graph_identity import GraphError

from packages.tests.codex_completion_fixture import IDENTITY, CompletionFixture, assemble_test_retro
from packages.tests.codex_completion_head_case import assert_changed_head, assert_empty_proof_disposition
from packages.tests.codex_fixture import (
    complete,
    frozen_evals,
    read_json,
    verify_completion,
    write_json,
)
from scripts.lib import proof_results as pr
from scripts.lib import retro, retro_check, teardown_steps


class CompletionTests(CompletionFixture):
    """Only current native evidence and successful observed proofs permit completion."""

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
            validate_completion_evidence(
                read_json(self.path), current["revision"], self.evals, self.proof, self.retro, self.transcript
            )
        complete(*self.arguments)

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
            state = read_json(self.path)
            validate_completion_evidence(
                state, state["completion"]["revision"], self.evals, self.proof, self.retro, self.transcript
            )  # removing this one gate would admit the hand-written retro

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
