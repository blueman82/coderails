"""Exercise neutral grading, amendment attestation and atomic failure behavior."""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.post_evals_fixture import ArtifactCase, entry
from scripts.lib.artifact_io import write_object
from scripts.lib.eval_artifact import grading_checksum
from scripts.post_evals import compute_and_validate_result, grade_loop


class GradingTests(ArtifactCase):
    """A grade reflects P0 outcomes and attested changes, never asserted success."""

    def test_neutral_results_and_independent_checksum(self) -> None:
        """Compute a separate canonical projection and verify the persisted stamp."""
        self.assertEqual(grade_loop(self.path), "GO")
        graded = self.reload()
        canonical = json.dumps(
            [{"id": "E1", "priority": "P0", "status": "pass"}], sort_keys=True, separators=(",", ":")
        )
        checksum = hashlib.sha256(f"{canonical}\nGO".encode()).hexdigest()
        self.assertEqual(graded["grading"]["checksum"], checksum)
        self.assertEqual(graded["grading"]["by"], "post_evals.py grade-loop")
        self.assertRegex(graded["graded_at"], r"^\d{4}-\d\d-\d\dT.*Z$")
        self.assertEqual(graded["grading"]["amendments_at_grade"], 0)
        self.assertEqual(grading_checksum(self.path, "GO"), checksum)
        self.assertNotEqual(grading_checksum(self.path, "NO-GO"), checksum)
        self.data["evals"] = [{**entry(), "status": "fail"}]
        self.save()
        self.assertEqual(compute_and_validate_result(self.path), "NO-GO")
        self.assertEqual(grade_loop(self.path), "NO-GO")
        self.assertNotEqual(grading_checksum(self.path, "GO"), checksum)
        self.data.update(verification_level=0, evals=[])
        self.save()
        self.assertEqual(grade_loop(self.path), "GO")

    def test_invalid_input_never_stamps(self) -> None:
        """Justification and head failures leave the input byte-for-byte intact."""
        for key in ("verification_justification", "head_sha"):
            with self.subTest(key=key):
                self.data[key] = ""
                self.save()
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, key):
                    grade_loop(self.path)
                self.assertEqual(self.path.read_bytes(), before)
                self.assertNotIn("grading", self.reload())
                self.data[key] = "valid"

    def test_atomic_replace_failure_preserves_input(self) -> None:
        """A failed final filesystem replacement cannot publish a partial verdict."""
        before = self.path.read_bytes()
        with (
            patch("os.replace", side_effect=PermissionError("fixture replacement denied")),
            self.assertRaisesRegex(PermissionError, "replacement denied"),
        ):
            grade_loop(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_amendments_before_first_grade_and_attested_growth(self) -> None:
        """Only amendments added after grading need an independent attestor."""
        self.data["amendments"] = [{"why": "initial"}, {"why": "initial second"}]
        self.save()
        grade_loop(self.path)
        self.data = self.reload()
        self.assertEqual(self.data["grading"]["amendments_at_grade"], 2)
        self.data["amendments"].append({"why": "new", "regraded_by": "independent native reviewer"})
        self.save()
        self.assertEqual(grade_loop(self.path), "GO")
        self.assertEqual(self.reload()["grading"]["amendments_at_grade"], 3)

    def test_unattested_growth_rejected_without_mutation(self) -> None:
        """Missing, blank and non-string reviewer identities never authorize a regrade."""
        grade_loop(self.path)
        baseline = self.reload()
        for identity in (None, "", " \t", 123):
            with self.subTest(identity=identity):
                self.data = {**baseline, "amendments": [{"why": "new", "regraded_by": identity}]}
                self.save()
                before = self.path.read_bytes()
                with self.assertRaisesRegex(ValueError, "regraded_by"):
                    grade_loop(self.path)
                self.assertEqual(self.path.read_bytes(), before)

    def test_grade_residue_and_legacy_count_cannot_bypass_attestation(self) -> None:
        """Removing one stamp field cannot hide that this artifact was graded."""
        grade_loop(self.path)
        baseline = self.reload()
        for removed in ("grading", "graded_at", "result"):
            self.data = {**baseline, "amendments": [{"why": "unattested"}]}
            self.data.pop(removed)
            self.save()
            with self.subTest(removed=removed), self.assertRaisesRegex(ValueError, "regraded_by"):
                grade_loop(self.path)
        self.data = {**baseline, "grading": {"by": "previous"}, "amendments": [{"why": "new"}]}
        self.save()
        with self.assertRaisesRegex(ValueError, "regraded_by"):
            grade_loop(self.path)

    def test_unparseable_progress_refuses_grading_and_leaves_suite_unchanged(self) -> None:
        """An unreadable sibling progress.json must not yield a grade without loop identity."""
        progress = Path(self.path).with_name("progress.json")
        progress.write_text("{not json", encoding="utf-8")
        before = Path(self.path).read_bytes()
        with self.assertRaisesRegex(ValueError, "does not parse"):
            grade_loop(self.path)
        self.assertEqual(Path(self.path).read_bytes(), before)
        progress.unlink()
        with self.assertRaisesRegex(ValueError, "progress_missing"):
            grade_loop(self.path)
        self.assertEqual(Path(self.path).read_bytes(), before)

    def test_malformed_or_mixed_amendments(self) -> None:
        """Malformed amendment collections and partially attested batches fail closed."""
        grade_loop(self.path)
        baseline = self.reload()
        for amendments in (2.5, ["bad"], [{"regraded_by": "reviewer"}, {"why": "unattested"}]):
            with self.subTest(amendments=amendments):
                self.data = {**baseline, "amendments": amendments}
                self.save()
                before = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    grade_loop(self.path)
                self.assertEqual(self.path.read_bytes(), before)

    def test_status_change_without_amendment_recomputes_verdict(self) -> None:
        """Repeated grading without new amendments still recomputes actual P0 status."""
        grade_loop(self.path)
        self.data = self.reload()
        self.data["evals"][0]["status"] = "fail"
        self.save()
        self.assertEqual(grade_loop(self.path), "NO-GO")

    def test_owner_identity_is_stamped_without_affecting_checksum(self) -> None:
        """Read current sibling identity while preserving the verdict projection."""
        expected = grading_checksum(self.path, "GO")
        write_object(
            self.directory / "progress.json",
            {"schema_version": 3, "session_id": "session", "loop_id": "loop", "revision": 4},
        )
        grade_loop(self.path)
        graded = self.reload()
        self.assertEqual([graded[key] for key in ("session_id", "loop_id", "revision")], ["session", "loop", 4])
        self.assertEqual(graded["grading"]["checksum"], expected)


if __name__ == "__main__":
    unittest.main()
