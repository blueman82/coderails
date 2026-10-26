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
import graph_dispatch
from graph_artifacts import validate_completion_evidence, validate_evals
from graph_identity import GraphError

from packages.tests.codex_fixture import (
    append,
    complete,
    frozen_evals,
    read_json,
    spawn,
    state,
    transcripts,
    verify_completion,
    write_json,
)
from scripts.lib import proof_results as pr

IDENTITY = {"session_id": "parent", "loop_id": "loop"}


class CompletionTests(unittest.TestCase):
    """Only current native evidence and successful observed proofs permit completion."""

    def setUp(self) -> None:
        """Create a completed worker with independent proof and eval artifacts."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        previous = Path.cwd()
        subprocess.run(["git", "init", "-q", str(self.directory)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(self.directory),
                "-c",
                "user.name=Fixture",
                "-c",
                "user.email=fixture@example.test",
                "commit",
                "-q",
                "--allow-empty",
                "-m",
                "fixture",
            ],
            check=True,
        )
        config = self.directory / ".coderails/workflow.config.yaml"
        config.parent.mkdir()
        config.write_text("memory:\n  backend: off\n")
        os.chdir(self.directory)
        self.addCleanup(os.chdir, previous)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "loops/project/parent/progress.json"
        self.path.parent.mkdir(parents=True)
        write_json(self.path, state())
        self.evals = self.path.with_name("evals.json")
        write_json(self.evals, frozen_evals())
        parent = transcripts(self.directory)
        graph_dispatch.begin_wave(self.path)
        self.child = spawn(parent, read_json(self.path))
        graph_dispatch.record_wave(
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
        write_json(self.retro, {"schema_version": 2, "session_id": "parent", "loop_id": "loop", "status": "complete"})
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

    def test_changed_head_invalidates_codex_completion(self) -> None:
        """Revalidation refuses a proof that passed before this worktree advanced."""
        subprocess.run(["git", "-C", str(self.directory), "init", "-q"], check=True)

        def commit(message: str) -> None:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.directory),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.com",
                    "commit",
                    "--allow-empty",
                    "-qm",
                    message,
                ],
                check=True,
            )

        commit("first")
        before = Path.cwd()
        try:
            os.chdir(self.directory)
            self.proof_result("satisfied")
            complete(*self.arguments)
            commit("second")
            with self.assertRaisesRegex(GraphError, r"P1\(proof_stale_head\)"):
                verify_completion(*self.arguments)
        finally:
            os.chdir(before)

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
        current = read_json(self.path)
        rejected: tuple[object, ...] = (None, "none", "none: ")
        for disposition in rejected:
            write_json(self.path, current | {"proof_disposition": disposition})
            with self.assertRaisesRegex(GraphError, "proof_disposition_no_reason"):
                complete(*self.arguments)
        typed = {"kind": "none", "reason_code": "docs_only", "reason": "documentation only"}
        accepted: tuple[object, ...] = ("none: no executable surface", typed)
        for disposition in accepted:
            write_json(self.path, current | {"proof_disposition": disposition})
            validate_completion_evidence(
                read_json(self.path), current["revision"], self.evals, self.proof, self.retro, self.transcript
            )
        complete(*self.arguments)

    def test_empty_proof_file_uses_a_valid_disposition(self) -> None:
        """An owned empty proof document follows the same disposition rule as Claude."""
        self.document["proofs"] = []
        write_json(self.proof, self.document)
        current = read_json(self.path)
        write_json(
            self.path,
            current
            | {"proof_disposition": {"kind": "none", "reason_code": "docs_only", "reason": "no executable proof"}},
        )
        complete(*self.arguments)

    def test_disposition_does_not_hide_unobserved_withdrawal(self) -> None:
        """Codex completion requires an observed failed run for a withdrawn proof."""
        self.document["withdrawn_proofs"] = [
            {"id": "P1", "cmd": "true", "withdrawn_reason": "cannot satisfy the requirement"}
        ]
        self.document["proofs"] = []
        write_json(self.proof, self.document)
        self.results.unlink()
        pr.append(self.results, kind="freeze", proof_json_sha256=pr.doc_sha(self.document), **IDENTITY)
        current = read_json(self.path)
        write_json(self.path, current | {"proof_disposition": "none: no executable surface"})
        with self.assertRaisesRegex(GraphError, r"P1\(proof_withdrawn_unobserved\)"):
            complete(*self.arguments)
        self.proof_result("failed")
        complete(*self.arguments)

    def test_proof_array_shape_and_combined_cap(self) -> None:
        """Codex completion enforces both proof arrays and the shared count cap."""
        cases: tuple[tuple[dict[str, Any], str], ...] = (
            ({"withdrawn_proofs": {}}, "withdrawn_proofs"),
            (
                {
                    "withdrawn_proofs": [
                        {"id": f"W{i}", "cmd": "false", "withdrawn_reason": "failed"} for i in range(100)
                    ]
                },
                "100",
            ),
        )
        for change, reason in cases:
            with self.subTest(change=reason):
                write_json(self.proof, self.document | change)
                with self.assertRaisesRegex(GraphError, reason):
                    complete(*self.arguments)

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
