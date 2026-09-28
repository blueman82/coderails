#!/usr/bin/env python3
"""Pin proof cap, identity, shape, and anti-gaming boundaries from the original Stop suite."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_completion import validate_work_units
from hooks.scripts.lib.loop_proofs import validate_proofs
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


class ProofBoundaryTests(HookTestCase):
    """A recorded assertion cannot substitute for an actual final foreground tool result."""

    def setUp(self) -> None:
        """Create separately owned proof and native transcript fixture files."""
        super().setUp()
        self.proof = self.directory / "proof.json"
        self.trace = self.directory / "transcript.jsonl"
        self.state: dict[str, Any] = {"schema_version": 3, "proof_disposition": "none"}

    def record(
        self,
        command: str = "run proof",
        identifier: object = "native-id",
        result_id: object = "native-id",
        background: object = False,
        result: bool = True,
    ) -> None:
        """Write one exact native execution/result pair, including deliberate malformed fields."""
        use = {
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
        }
        response = {
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": result_id, "is_error": False}]},
        }
        self.trace.write_text(json.dumps(use) + "\n42\n" + (json.dumps(response) + "\n" if result else ""))

    def test_unusable_native_ids_results_and_background_types(self) -> None:
        """Missing results, unusable IDs, echoes, and non-boolean background values cannot pass."""
        self.proof.write_text(
            json.dumps({"schema_version": 1, "proofs": [{"id": "P1", "cmd": "run proof", "status": "pass"}]})
        )
        rows: list[dict[str, Any]] = [
            {"identifier": None},
            {"result_id": None},
            {"result": False},
            {"background": "true"},
            {"background": ""},
            {"background": 0},
            {"command": "echo run proof"},
            {"command": "run proof && echo done"},
        ]
        for row in rows:
            self.record(**row)
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, "P1\\(unexecuted\\)"):
                validate_proofs(self.proof, self.state, str(self.trace))
        self.record(command="  run proof  ")
        self.assertEqual(validate_proofs(self.proof, self.state, str(self.trace)), "")

    def test_bad_proof_fields_and_fallback_identifiers(self) -> None:
        """Invalid commands fail closed, while absent/non-string IDs retain indexed diagnostics."""
        self.record()
        invalid: list[object] = [None, "", " ", 42, True, [], {}]
        for command in invalid:
            self.proof.write_text(json.dumps({"schema_version": 1, "proofs": [{"id": "P4", "cmd": command}]}))
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "P4\\(badcmd\\)"):
                validate_proofs(self.proof, self.state, str(self.trace))
        for identifier in (None, 42):
            self.proof.write_text(json.dumps({"schema_version": 1, "proofs": [{"id": identifier, "cmd": "missing"}]}))
            with self.assertRaisesRegex(ValueError, "P0\\(unexecuted\\)"):
                validate_proofs(self.proof, self.state, str(self.trace))
        self.proof.write_text(json.dumps({"schema_version": 1, "proofs": ["scalar"]}))
        with self.assertRaisesRegex(ValueError, "P0\\(unverifiable\\)"):
            validate_proofs(self.proof, self.state, str(self.trace))

    def test_cap_and_mixed_proof_diagnostics(self) -> None:
        """The inclusive cap survives large unrelated transcripts, and only offenders are named."""
        self.record()
        with self.trace.open("a") as stream:
            for _ in range(500):
                stream.write(
                    json.dumps(
                        {
                            "type": "assistant",
                            "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]},
                        }
                    )
                    + "\n"
                )
        proofs = [{"id": f"P{index}", "cmd": "run proof"} for index in range(100)]
        self.proof.write_text(json.dumps({"schema_version": 2, "proofs": proofs}))
        self.assertEqual(validate_proofs(self.proof, self.state, str(self.trace)), "")
        self.proof.write_text(json.dumps({"schema_version": 1, "proofs": proofs, "withdrawn_proofs": [{}]}))
        with self.assertRaisesRegex(ValueError, "101.*100"):
            validate_proofs(self.proof, self.state, str(self.trace))
        self.proof.write_text(
            json.dumps(
                {"schema_version": 1, "proofs": [{"id": "GOOD", "cmd": "run proof"}, {"id": "BAD", "cmd": "missing"}]}
            )
        )
        with self.assertRaises(ValueError) as error:
            validate_proofs(self.proof, self.state, str(self.trace))
        self.assertIn("BAD", str(error.exception))
        self.assertNotIn("GOOD", str(error.exception))

    def test_independent_unit_shapes_reasons_and_compounded_diagnostics(self) -> None:
        """Malformed siblings cannot hide unfinished units; completed siblings stay out of diagnostics."""
        invalid: list[object] = [42, True, [], {}, None, " "]
        for reason in invalid:
            with self.assertRaisesRegex(ValueError, "bad, pending"):
                validate_work_units(
                    {
                        "work_units": {
                            "bad": {"status": "dropped", "dropped_reason": reason},
                            "pending": {"status": "pending"},
                            "good": {"status": "done"},
                        }
                    }
                )
        for unit in ("scalar", 42, None, {"status": "blocked"}, {"status": "in-progress"}):
            with self.assertRaises(ValueError) as error:
                validate_work_units({"work_units": {"bad": unit, "good": {"status": "done"}}})
            self.assertIn("bad", str(error.exception))
            self.assertNotIn("good", str(error.exception))


if __name__ == "__main__":
    unittest.main()
