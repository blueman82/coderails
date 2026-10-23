"""Preserve identity-bound eval/proof/retro completion through native graph and Stop APIs."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.tests.claude_graph_test_support import ROOT, GraphCase, dispatch, fixture, load
from hooks.scripts.tests.lib import assembled_retro
from scripts.lib import proof_results as pr
from scripts.lib import retro, teardown_steps
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
    proofs = {**identity, "schema_version": 2, "proofs": [{"id": "P1", "cmd": "true", "expect": {"exit_code": 0}}]}
    fixture.write_json(case.path.with_name("proof.json"), proofs)
    results = case.path.with_name(pr.RESULTS_NAME)
    results.unlink(missing_ok=True)
    digest = pr.doc_sha(proofs)
    pr.append(results, kind="freeze", proof_json_sha256=digest, **identity)
    pr.append(
        results,
        kind="run",
        proof_id="P1",
        cmd_sha256=pr.sha("true"),
        proof_json_sha256=digest,
        verdict="satisfied",
        cwd=str(Path.cwd()),
        head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        **identity,
    )
    prepared_retro(case, state["session_id"])


def prepared_retro(case: GraphCase, session: str) -> dict[str, Any]:
    """Freeze a correctly owned D4 preparation receipt after the fixture sources are final."""
    state_dir = case.path.parent
    assembled_retro.write(state_dir, session)
    state: dict[str, Any] = json.loads(case.path.read_text(encoding="utf-8"))
    loop_id = str(state["loop_id"])
    source = dict(state)
    for key in ("status", "completion", "completed_marker"):
        source.pop(key, None)
    if isinstance(source.get("loop_stop_counts"), dict):
        source["loop_stop_counts"].pop("complete", None)
    binding = {
        "repo_dir": str(state_dir.parent.resolve()),
        "state_dir": str(state_dir.resolve()),
        "session_id": session,
        "loop_id": loop_id,
        "revision": state["revision"],
        "progress_sha256": teardown_steps.sha_json(source),
    }
    prepared: dict[str, Any] = {"schema": 1, "binding": binding, "records": []}
    prep_path = state_dir / f"orders-prepared-{hashlib.sha256(loop_id.encode()).hexdigest()}.json"
    prep_path.write_text(json.dumps(prepared), encoding="utf-8")
    row = {
        "step": "orders_prepared",
        **{key: binding[key] for key in ("session_id", "loop_id", "revision")},
        "binding": binding,
        "evidence_sha256": teardown_steps.sha_json(prepared),
        "ts": "2026-10-19T00:00:00+00:00",
    }
    with (state_dir / teardown_steps.NAME).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")
    with patch.dict(os.environ, {"PATH": "/nonexistent"}):
        payload, code = retro.assemble(state_dir, session)
    if code == 2:
        raise AssertionError(payload)
    return cast("dict[str, Any]", json.loads((state_dir / "retro.json").read_text(encoding="utf-8")))


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
        prepared_retro(self, "fixture-session")  # bind the removed file's absence before reassembly
        with self.assertRaisesRegex(ValueError, "no proof_disposition"):
            dispatch.complete(self.path, "fixture-session", write=False)
        self.save({**state, "proof_disposition": "none"})
        prepared_retro(self, "fixture-session")
        with self.assertRaisesRegex(ValueError, "no proof_disposition"):
            dispatch.complete(self.path, "fixture-session", write=False)
        docs = {"kind": "none", "reason_code": "docs_only", "reason": "docs"}
        for disposition in ("none: no executable surface", docs):
            self.save({**state, "proof_disposition": disposition})
            prepared_retro(self, "fixture-session")
            dispatch.complete(self.path, "fixture-session", write=False)
        for version in (1, 2):
            self.save({**state, "schema_version": version, "proof_disposition": "none: x"})
            prepared_retro(self, "fixture-session")
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
            prepared_retro(self, "fixture-session")
            with self.assertRaisesRegex(ValueError, "work_units"):
                dispatch.complete(self.path, "fixture-session", write=False)
        for units in ({}, {"unit": {"status": "done"}}, {"unit": {"status": "dropped", "dropped_reason": "duplicate"}}):
            self.save({**state, "work_units": units})
            prepared_retro(self, "fixture-session")  # recompute the disposition and preparation binding
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
            (
                {**original, "session_id": "foreign"},
                None,
                2,
                "proof_stale_cmd",
            ),  # the foreign doc no longer hashes to the freeze row
            (None, None, 2, "no proof_disposition"),
            (None, "none: no executable surface", 0, ""),
        )
        for document, disposition, expected, reason in cases:
            self.save({**state, "proof_disposition": disposition})
            if document is None:
                proof.unlink(missing_ok=True)
            else:
                fixture.write_json(proof, document)
            prepared_retro(self, "fixture-session")
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
