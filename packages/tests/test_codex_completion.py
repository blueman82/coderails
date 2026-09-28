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

from packages.tests.codex_fixture import append, frozen_evals, read_json, spawn, state, transcripts, write_json


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
        write_json(
            self.proof,
            {
                "session_id": "parent",
                "loop_id": "loop",
                "proofs": [{"id": "P1", "cmd": "true", "status": "pass", "evidence": "observed"}],
            },
        )
        write_json(self.retro, {"schema_version": 2, "session_id": "parent", "loop_id": "loop", "status": "complete"})
        self.transcript = self.path.with_name("proof.jsonl")
        append(self.transcript, {"type": "turn_context", "payload": {"loop_id": "loop"}})
        self.proof_result("proof", 0)
        self.arguments = (self.path, "parent", self.evals, self.proof, self.retro, self.transcript)

    def proof_result(self, call: str, code: int | None, loop: str = "loop") -> None:
        """Append a native proof call and its inner command result."""
        append(
            self.transcript,
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": call,
                    "input": 'const r = await tools.exec_command({cmd:"true"}); text(r);',
                },
            },
        )
        output = (
            json.dumps({"loop_id": loop, "exit_code": code})
            if code is not None
            else "Script completed\nProcess exited with code 1"
        )
        append(
            self.transcript,
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": call,
                    "output": [{"type": "input_text", "text": output}],
                },
            },
        )

    def test_success_and_revalidation(self) -> None:
        """A completed graph is revalidated against the latest proof outcome."""
        complete(*self.arguments)
        verify_completion(*self.arguments)
        self.proof_result("later", 1)
        with self.assertRaises(GraphError):
            verify_completion(*self.arguments)

    def test_outer_result_and_foreign_loop_cannot_pass(self) -> None:
        """Outer tool success never overrides an inner failed or foreign-loop command."""
        for code, loop in ((None, "loop"), (1, "loop"), (0, "foreign")):
            self.proof_result(f"next-{code}-{loop}", code, loop)
            before = self.path.read_bytes()
            with self.assertRaises(GraphError):
                complete(*self.arguments)
            self.assertEqual(before, self.path.read_bytes())

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
            {"proofs": [{"status": "fail"}]},
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
                self.proof_result("failure", 1)
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
