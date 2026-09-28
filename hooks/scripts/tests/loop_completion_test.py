#!/usr/bin/env python3
"""Exercise completion proof provenance, independent work units, retrospectives, and eval stamps."""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_completion import cost_message, validate_completion, validate_work_units
from hooks.scripts.lib.loop_evals import read_loop_evals_result
from hooks.scripts.lib.loop_proofs import validate_proofs
from hooks.scripts.lib.loop_state_common import LoopState
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.eval_artifact import grading_checksum


class CompletionTests(HookTestCase):
    """Ensure declarations cannot replace real proof executions or a frozen eval grade."""

    def setUp(self) -> None:
        """Write native proof tool-use/result pairs and the owning state/artifacts."""
        super().setUp()
        self.path = self.progress(proof_disposition="none: no executable surface")
        self.state = LoopState(self.path, "S1", 1, json.loads(self.path.read_text()))
        self.retro = self.path.with_name("retro.json")
        self.retro.write_text('{"schema_version":2}')
        self.proof = self.path.with_name("proof.json")
        self.trace = self.directory / "proof-transcript.jsonl"
        self.trace.write_text("")

    def execution(self, identifier: str, command: str, error: object = False, background: bool = False) -> None:
        """Append native foreground or background execution and its paired result."""
        with self.trace.open("a") as stream:
            for record in (
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Bash",
                                "id": identifier,
                                "input": {"command": command, "run_in_background": background},
                            }
                        ]
                    },
                },
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": identifier, "is_error": error}]},
                },
            ):
                stream.write(json.dumps(record) + "\n")

    def test_absent_retro_and_proof_disposition(self) -> None:
        """Absent proof needs an explicit recorded skip; retro remains mandatory."""
        self.assertEqual(validate_completion(self.state, str(self.trace)), ["cost not recorded"])
        self.state.data.pop("proof_disposition")
        with self.assertRaisesRegex(ValueError, "no proof.json"):
            validate_completion(self.state, str(self.trace))
        dispositions: list[object] = ["expected", "None", "", [], 1]
        for disposition in dispositions:
            self.state.data["proof_disposition"] = disposition
            with self.assertRaises(ValueError):
                validate_proofs(self.proof, self.state.data, str(self.trace))
        for disposition in ("none", "none: reason"):
            self.state.data["proof_disposition"] = disposition
            self.assertEqual(validate_proofs(self.proof, self.state.data, str(self.trace)), "")
        self.retro.unlink()
        with self.assertRaisesRegex(ValueError, "retro.json is absent"):
            validate_completion(self.state, str(self.trace))

    def test_independent_work_units_are_strict(self) -> None:
        """Only objects containing done or reasoned dropped units pass current-schema completion."""
        for units in (
            None,
            {},
            {"U3[1]": {"status": "done"}},
            {"U3[2]": {"status": "dropped", "dropped_reason": "superseded"}},
        ):
            validate_work_units({"work_units": units})
        invalid: list[object] = [
            [],
            "done",
            1,
            {"x": "done"},
            {"x": {"status": "pending"}},
            {"x": {"status": "dropped"}},
            {"x": {"status": "dropped", "dropped_reason": " "}},
            {"x": {"status": "completed"}},
        ]
        for invalid_units in invalid:
            with self.subTest(units=invalid_units), self.assertRaises(ValueError):
                validate_work_units({"work_units": invalid_units})

    def test_malformed_proof_shapes_and_cap(self) -> None:
        """Bad proof documents, bad array fields, and excessive combined counts fail closed."""
        cases: list[object] = [
            [],
            {},
            {"schema_version": "1"},
            {"schema_version": True},
            {"schema_version": 1, "proofs": {}},
            {"schema_version": 1, "withdrawn_proofs": "bad"},
            {"schema_version": 1, "proofs": [{}] * 51, "withdrawn_proofs": [{}] * 50},
        ]
        for document in cases:
            self.proof.write_text(json.dumps(document))
            with self.subTest(document=document), self.assertRaises(ValueError):
                validate_proofs(self.proof, self.state.data, str(self.trace))
        self.proof.write_text("{broken")
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_proofs(self.proof, self.state.data, str(self.trace))
        self.proof.write_text('{"schema_version":1,"proofs":null,"withdrawn_proofs":null}')
        self.assertEqual(validate_proofs(self.proof, self.state.data, str(self.trace)), "")

    def test_exact_foreground_and_final_attempt_provenance(self) -> None:
        """Missing, background, command mismatch, and latest-failed proof attempts block."""
        self.proof.write_text(json.dumps({"schema_version": 1, "proofs": [{"id": "P1", "cmd": "python3 verify.py"}]}))
        for label in ("unexecuted", "background", "wrong_command"):
            if label == "background":
                self.execution("a", "python3 verify.py", background=True)
            elif label == "wrong_command":
                self.execution("b", "python3 other.py")
            with self.assertRaisesRegex(ValueError, "unexecuted"):
                validate_proofs(self.proof, self.state.data, str(self.trace))
        self.execution("c", "  python3 verify.py  ")
        self.assertEqual(validate_proofs(self.proof, self.state.data, str(self.trace)), "")
        self.execution("d", "python3 verify.py", error=True)
        with self.assertRaisesRegex(ValueError, "failed"):
            validate_proofs(self.proof, self.state.data, str(self.trace))
        self.execution("e", "python3 verify.py", error=None)
        self.assertEqual(validate_proofs(self.proof, self.state.data, str(self.trace)), "")

    def test_withdrawn_proofs_require_failure_reason_and_distinct_id(self) -> None:
        """Withdrawal requires an observed last failure and contributes one human disclosure."""
        document: dict[str, Any] = {
            "schema_version": 1,
            "proofs": [],
            "withdrawn_proofs": [
                {"id": "W1", "cmd": "python3 control.py", "withdrawn_reason": "invalid assumption\nmore context"}
            ],
        }
        self.proof.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "unexecuted"):
            validate_proofs(self.proof, self.state.data, str(self.trace))
        self.execution("a", "python3 control.py", error=False)
        with self.assertRaisesRegex(ValueError, "not_failed"):
            validate_proofs(self.proof, self.state.data, str(self.trace))
        self.execution("b", "python3 control.py", error=True)
        self.assertEqual(
            validate_proofs(self.proof, self.state.data, str(self.trace)), "Withdrawn proofs: W1: invalid assumption"
        )
        for change, reason in (({"withdrawn_reason": ""}, "badreason"), ({"cmd": ""}, "badcmd")):
            changed = copy.deepcopy(document)
            changed["withdrawn_proofs"][0].update(change)
            self.proof.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, reason):
                validate_proofs(self.proof, self.state.data, str(self.trace))
        document["proofs"] = [{"id": "W1", "cmd": "python3 control.py"}]
        self.proof.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError, "duplicate_id"):
            validate_proofs(self.proof, self.state.data, str(self.trace))

    def test_frozen_evals_do_not_pass_completion_and_stamps_detect_drift(self) -> None:
        """Frozen suites authorize dispatch only; justification and exact grading checksums remain required."""
        path = self.path.with_name("evals.json")
        suite: dict[str, Any] = {
            "scope": "loop",
            "verification_level": 1,
            "verification_justification": "executable hook",
            "frozen_sha": "a" * 40,
            "evals": [
                {
                    "id": "E1",
                    "priority": "P0",
                    "mode": "scripted",
                    "cmd": "python3 check.py",
                    "negative_control": "python3 fail.py",
                    "status": "pass",
                }
            ],
        }
        path.write_text(json.dumps(suite))
        with patch.dict(os.environ, self.environment):
            self.assertEqual(read_loop_evals_result(path.parent), "FROZEN")
            suite["result"] = "GO"
            path.write_text(json.dumps(suite))
            self.assertEqual(read_loop_evals_result(path.parent), "UNSTAMPED")
            suite["grading"] = {"by": "post_evals.py grade-loop", "checksum": grading_checksum(path, "GO")}
            path.write_text(json.dumps(suite))
            self.assertEqual(read_loop_evals_result(path.parent), "GO")
            suite["evals"][0]["status"] = "fail"
            path.write_text(json.dumps(suite))
            self.assertEqual(read_loop_evals_result(path.parent), "UNSTAMPED")
            suite["grading"]["checksum"] = grading_checksum(path, "GO")
            path.write_text(json.dumps(suite))
            self.assertEqual(read_loop_evals_result(path.parent), "NO-GO")
            suite["verification_justification"] = " "
            path.write_text(json.dumps(suite))
            self.assertEqual(read_loop_evals_result(path.parent), "UNJUSTIFIED")

    def test_cost_disclosures_are_frozen_and_single_line(self) -> None:
        """Cost reporting distinguishes missing/incomplete values and sanitizes output."""
        self.assertEqual(cost_message({"schema_version": 1}), "")
        self.assertEqual(cost_message({"schema_version": 2}), "cost not recorded")
        self.assertIn("unavailable", cost_message({"schema_version": 2, "cost": {}}))
        self.assertIn("incomplete", cost_message({"schema_version": 2, "cost": {"total_tokens": 100}}))
        message = cost_message(
            {
                "schema_version": 2,
                "cost": {"total_tokens": "10\nline", "total_usd_estimate": 1.234, "prices_as_of": "2020-01-01"},
            }
        )
        self.assertIn("$1.23", message)
        self.assertNotIn("\n", message)
        self.assertIn("verify at claude.com/pricing", message)


if __name__ == "__main__":
    unittest.main()
