#!/usr/bin/env python3
"""Pin proof cap, identity, shape, and anti-gaming boundaries from the original Stop suite."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_completion import validate_work_units
from hooks.scripts.lib.loop_proofs import validate_proofs
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib import proof_results as pr


class ProofBoundaryTests(HookTestCase):
    """A proof is released only by a controller-recorded run row on a valid chain; shape and cap stay strict."""

    def setUp(self) -> None:
        """Create the proof file, its results chain location and a state bound to one session and loop."""
        super().setUp()
        self.proof = self.directory / "proof.json"
        self.results = self.directory / pr.RESULTS_NAME
        self.state: dict[str, Any] = {"schema_version": 3, "session_id": "s", "loop_id": "l"}

    def freeze(self, document: dict[str, Any], run: bool = True, verdict: str = "satisfied") -> None:
        """Write the document, a freeze row, and (optionally) a run row for each well-formed proof."""
        document.setdefault("session_id", "s")
        document.setdefault("loop_id", "l")
        self.proof.write_text(json.dumps(document))
        self.results.unlink(missing_ok=True)
        digest = pr.doc_sha(document)
        pr.append(self.results, kind="freeze", proof_json_sha256=digest, session_id="s", loop_id="l")
        raws: list[object] = document.get("proofs") or []
        for raw in raws:
            item = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
            cmd, identifier = item.get("cmd"), item.get("id")
            if run and isinstance(cmd, str) and isinstance(identifier, str):
                pr.append(
                    self.results,
                    kind="run",
                    proof_id=identifier,
                    cmd_sha256=pr.sha(cmd.strip()),
                    proof_json_sha256=digest,
                    session_id="s",
                    loop_id="l",
                    verdict=verdict,
                    cwd=str(Path.cwd()),
                    head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                )

    def test_missing_failed_and_untrusted_rows_do_not_pass(self) -> None:
        """No run row, a failed verdict, a foreign session, or whitespace-padded cmd handling are exact."""
        document = {"schema_version": 2, "proofs": [{"id": "P1", "cmd": "run proof"}]}
        self.freeze(document, run=False)
        with self.assertRaisesRegex(ValueError, "P1\\(proof_unexecuted\\)"):
            validate_proofs(self.proof, self.state, "")
        self.freeze(document, verdict="failed")
        with self.assertRaisesRegex(ValueError, "P1\\(proof_failed\\)"):
            validate_proofs(self.proof, self.state, "")
        self.freeze(document)
        self.assertEqual(validate_proofs(self.proof, self.state, ""), "")
        self.assertRaises(ValueError, validate_proofs, self.proof, self.state | {"session_id": "other"}, "")
        self.freeze({"schema_version": 2, "proofs": [{"id": "P1", "cmd": "  run proof \n"}]})
        self.assertEqual(validate_proofs(self.proof, self.state, ""), "")

    def test_bad_proof_fields_and_fallback_identifiers(self) -> None:
        """Invalid commands fail closed, while absent/non-string IDs retain indexed diagnostics."""
        invalid: list[object] = [None, "", " ", 42, True, [], {}]
        for command in invalid:
            self.freeze({"schema_version": 2, "proofs": [{"id": "P4", "cmd": command}]})
            with self.subTest(command=command), self.assertRaisesRegex(ValueError, "P4\\(proof_stale_cmd\\)"):
                validate_proofs(self.proof, self.state, "")
        for identifier in (None, 42):
            self.freeze({"schema_version": 2, "proofs": [{"id": identifier, "cmd": "missing"}]}, run=False)
            with self.assertRaisesRegex(ValueError, "P0\\(proof_unexecuted\\)"):
                validate_proofs(self.proof, self.state, "")
        self.freeze({"schema_version": 2, "proofs": ["scalar"]})
        with self.assertRaisesRegex(ValueError, "P0\\(proof_stale_cmd\\)"):
            validate_proofs(self.proof, self.state, "")

    def test_cap_and_mixed_proof_diagnostics(self) -> None:
        """The inclusive cap holds, and only offenders are named."""
        proofs = [{"id": f"P{index}", "cmd": "run proof"} for index in range(100)]
        self.freeze({"schema_version": 2, "proofs": proofs})
        self.assertEqual(validate_proofs(self.proof, self.state, ""), "")
        self.proof.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_id": "s",
                    "loop_id": "l",
                    "proofs": proofs,
                    "withdrawn_proofs": [{}],
                }
            )
        )
        with self.assertRaisesRegex(ValueError, "101.*100"):
            validate_proofs(self.proof, self.state, "")
        document = {
            "schema_version": 2,
            "proofs": [{"id": "GOOD", "cmd": "run proof"}, {"id": "BAD", "cmd": "missing"}],
        }
        self.freeze(document)
        pr.append(
            self.results,
            kind="run",
            proof_id="BAD",
            cmd_sha256=pr.sha("other"),
            session_id="s",
            loop_id="l",
            proof_json_sha256=pr.doc_sha(document),
            verdict="satisfied",
        )
        with self.assertRaises(ValueError) as error:
            validate_proofs(self.proof, self.state, "")
        self.assertIn("BAD", str(error.exception))
        self.assertNotIn("GOOD", str(error.exception))

    def test_disposition_does_not_hide_unobserved_withdrawal(self) -> None:
        """Even with no live proofs, a withdrawn proof needs a failed controller run."""
        document = {
            "schema_version": 2,
            "proofs": [],
            "withdrawn_proofs": [{"id": "W1", "cmd": "false", "withdrawn_reason": "unsupported"}],
        }
        self.freeze(document)
        state = self.state | {"proof_disposition": "none: no executable surface"}
        with self.assertRaisesRegex(ValueError, r"W1\(proof_withdrawn_unobserved\)"):
            validate_proofs(self.proof, state)
        pr.append(
            self.results,
            kind="run",
            proof_id="W1",
            cmd_sha256=pr.sha("false"),
            proof_json_sha256=pr.doc_sha(document),
            session_id="s",
            loop_id="l",
            verdict="failed",
            cwd=str(Path.cwd()),
            head_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        )
        self.assertIn("W1: unsupported", validate_proofs(self.proof, state))

    def test_present_proof_needs_nonblank_matching_identity(self) -> None:
        """Claude proof validation requires the same nonblank loop identity as the graph."""
        document = {"schema_version": 2, "proofs": [{"id": "P1", "cmd": "true"}]}
        for field, value in (("session_id", ""), ("loop_id", " "), ("session_id", "other")):
            with self.subTest(field=field, value=value):
                self.freeze(document | {"session_id": "s", "loop_id": "l", field: value})
                with self.assertRaisesRegex(ValueError, "identity|session_id|loop_id"):
                    validate_proofs(self.proof, self.state)
        self.freeze(document | {"session_id": "s"})
        self.proof.write_text(json.dumps(document | {"session_id": "s"}))
        with self.assertRaisesRegex(ValueError, "loop_id"):
            validate_proofs(self.proof, self.state)

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
