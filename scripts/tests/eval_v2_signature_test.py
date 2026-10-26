"""A level-one-or-higher v2 freeze must have a trusted signature at every local consumer."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.lib import eval_level, eval_validation  # noqa: E402
from scripts.lib.eval_execution import record_smoke  # noqa: E402
from scripts.lib.eval_integrity import IntegrityError, suite_hash  # noqa: E402
from scripts.lib.eval_signing import KEY_MISSING, SigningError  # noqa: E402
from scripts.tests.eval_level_test import RepoCase  # noqa: E402


class V2SignatureTests(RepoCase):
    """Unsigned v2 suites cannot cross local freeze or merge boundaries."""

    def unsigned_suite(self) -> dict[str, object]:
        """Build a hash-consistent suite with no signature in a real repository."""
        data: dict[str, object] = {
            "integrity_version": 2,
            "verification_level": 1,
            "frozen_sha": self.base,
            "frozen_at": "2026-10-07T00:00:00Z",
            "task_ref": "feature/x",
            "evals": [],
        }
        data["frozen_hash"] = suite_hash(data)
        return data

    def test_unsigned_early_v2_is_refused_by_both_local_checks(self) -> None:
        """An ancestor SHA cannot make an unsigned v2 suite trustworthy."""
        data = self.unsigned_suite()
        with self.assertRaises(IntegrityError) as check:
            eval_level.check_suite(data, "1")
        self.assertEqual(check.exception.code, "signature_missing")
        with self.assertRaises(IntegrityError) as timing:
            eval_validation.require_freeze_timing(data, self.base, self.dir)
        self.assertEqual(timing.exception.code, "signature_missing")

    def test_smoke_run_does_not_freeze_unsigned_v2_when_signing_fails(self) -> None:
        """Freeze must stop before writing a hash if the signer is unavailable."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evals.json"
            path.write_text(json.dumps(self.unsigned_suite() | {"frozen_hash": None}))
            with (
                mock.patch("scripts.lib.eval_signing.sign", side_effect=SigningError(KEY_MISSING)),
                self.assertRaises(IntegrityError) as caught,
            ):
                record_smoke(path)
            self.assertEqual(caught.exception.code, KEY_MISSING)
            self.assertIsNone(json.loads(path.read_text())["frozen_hash"])


if __name__ == "__main__":
    unittest.main()
