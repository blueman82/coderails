"""Preserve identity-bound eval/proof/retro completion through native graph and Stop APIs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.tests.claude_graph_test_support import ROOT, GraphCase, dispatch, fixture, load
from scripts.post_evals import grade_loop


def artifacts(case: GraphCase, state: dict[str, Any]) -> None:
    """Grade a real current loop suite and write matching empty proof/retro artifacts."""
    identity = {key: state[key] for key in ("session_id", "loop_id")}
    suite = {
        **identity,
        "schema_version": 1,
        "scope": "loop",
        "revision": state["revision"],
        "verification_level": 1,
        "verification_justification": "native integration",
        "frozen_sha": "a" * 40,
        "head_sha": "a" * 40,
        "amendments": [],
        "evals": [
            {
                "id": "E1",
                "priority": "P0",
                "mode": "scripted",
                "surface": "merged-state",
                "assert": "contract",
                "cmd": "true",
                "negative_control": "false",
                "status": "pass",
                "evidence": "actual fixture checks",
            }
        ],
    }
    fixture.write_json(case.path.with_name("evals.json"), suite)
    grade_loop(case.path.with_name("evals.json"))
    fixture.write_json(case.path.with_name("retro.json"), {**identity, "schema_version": 1, "status": "complete"})
    fixture.write_json(
        case.path.with_name("proof.json"), {**identity, "schema_version": 1, "proofs": [], "withdrawn_proofs": []}
    )


class ArtifactGateTests(GraphCase):
    """Make artifact refusals observable only after authentic graph completion passes."""

    def test_complete_artifact_identity_and_grade_gates(self) -> None:
        """Wrong owner, stale grade, malformed or altered artifacts leave status untouched."""
        state = self.finish()
        artifacts(self, state)
        dispatch.complete(self.path, "fixture-session", write=False)
        for filename in ("evals.json", "retro.json", "proof.json"):
            path = self.path.with_name(filename)
            original = json.loads(path.read_text())
            for key, value in (("session_id", "foreign"), ("loop_id", "foreign")):
                fixture.write_json(path, {**original, key: value})
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "another|identity|belongs"):
                    dispatch.complete(self.path, "fixture-session")
                self.assertEqual(before, self.path.read_bytes())
            fixture.write_json(path, original)
        path = self.path.with_name("evals.json")
        original = json.loads(path.read_text())
        for changes in (
            {"revision": 0},
            {"result": "NO-GO"},
            {"verification_justification": ""},
            {"grading": {"by": "handwritten", "checksum": "forged"}},
            {"amendments": [{"id": "x"}]},
        ):
            fixture.write_json(path, {**original, **changes})
            with self.assertRaises(ValueError):
                dispatch.complete(self.path, "fixture-session")
            self.assertEqual(load(self.path)["status"], "in-progress")
        fixture.write_json(path, original)
        dispatch.complete(self.path, "fixture-session")
        self.assertEqual(load(self.path)["status"], "complete")

    def test_proof_absence_disposition_and_owned_empty_proof(self) -> None:
        """Current graphs require a proof or explicit absence, with no v1 grandfathering."""
        state = self.finish()
        artifacts(self, state)
        self.path.with_name("proof.json").unlink()
        with self.assertRaisesRegex(ValueError, "no proof_disposition"):
            dispatch.complete(self.path, "fixture-session", write=False)
        for disposition in ("none", "none: no executable surface"):
            self.save({**state, "proof_disposition": disposition})
            dispatch.complete(self.path, "fixture-session", write=False)
        for version in (1, 2):
            self.save({**state, "schema_version": version, "proof_disposition": "none"})
            with self.assertRaisesRegex(ValueError, "schema_version must be 3"):
                dispatch.complete(self.path, "fixture-session", write=False)

    def test_independent_work_units_cannot_hide_behind_done_graph(self) -> None:
        """Graph completion does not imply all separate work units were finished."""
        state = self.finish()
        artifacts(self, state)
        bad_units: tuple[Any, ...] = (
            [],
            {"unit": {"status": "pending"}},
            {"unit": {"status": "merged"}},
            {"unit": {"status": "dropped", "dropped_reason": " "}},
        )
        for units in bad_units:
            self.save({**state, "work_units": units})
            with self.assertRaisesRegex(ValueError, "work_units"):
                dispatch.complete(self.path, "fixture-session", write=False)
        for units in ({}, {"unit": {"status": "done"}}, {"unit": {"status": "dropped", "dropped_reason": "duplicate"}}):
            self.save({**state, "work_units": units})
            dispatch.complete(self.path, "fixture-session", write=False)

    def test_stop_gate_proof_identity_and_absence(self) -> None:
        """Native Stop uses proof disposition without skipping present-file ownership."""
        state = self.finish()
        self.path = resolve_path(str(self.home), "fixture-session")
        self.save(state)
        artifacts(self, state)
        fixture.append(
            self.parent,
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}]
                },
            },
        )
        fixture.append(
            self.parent,
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "LOOP-STOP: complete — verified"}]}},
        )
        payload = {
            "session_id": "fixture-session",
            "cwd": str(self.home),
            "transcript_path": str(self.parent),
            "stop_hook_active": False,
        }
        proof = self.path.with_name("proof.json")
        original = json.loads(proof.read_text())
        cases = (
            (original, None, 0, ""),
            ({**original, "session_id": "foreign"}, None, 2, "another loop"),
            (None, None, 2, "no proof_disposition"),
            (None, "none: no executable surface", 0, ""),
        )
        for document, disposition, expected, reason in cases:
            self.save({**state, "proof_disposition": disposition})
            if document is None:
                proof.unlink(missing_ok=True)
            else:
                fixture.write_json(proof, document)
            result = subprocess.run(
                [sys.executable, str(ROOT / "hooks/scripts/loop_stall_guard.py")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "CLAUDE_HOOK_MAX_ATTEMPTS": "1"},
            )
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertIn(reason, result.stderr)


if __name__ == "__main__":
    unittest.main()
