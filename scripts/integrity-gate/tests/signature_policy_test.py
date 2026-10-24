"""CI attestation refuses bad suite signatures without a local trust list."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gate_policy_test import EvidenceFixture  # type: ignore[import-not-found]
from integrity_policy import gate_pr

from scripts.lib.eval_integrity import sign_suite


class SignaturePolicyTests(unittest.TestCase):
    """Exercise the real gate with an untrusted signed owner comment."""

    def test_invalid_signature_without_allowed_signers_cannot_attest(self) -> None:
        """A missing signer list cannot turn invalid bytes into a passing status."""
        client = EvidenceFixture()
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"CODERAILS_KEYS_DIR": directory}):
            sign_suite(client.document)
            lines = client.document["signature"]["sig"].splitlines()
            lines[2] = lines[2][:-4] + ("AAAA" if not lines[2].endswith("AAAA") else "BBBB")
            client.document["signature"]["sig"] = "\n".join(lines) + "\n"
            (Path(directory) / "allowed_signers").unlink()
            with redirect_stdout(io.StringIO()):
                self.assertEqual(gate_pr(client, 7, 204800, 720), 1)
        self.assertEqual(client.posts[-1][1], "error")
        self.assertIn("eval_evidence_invalid", client.posts[-1][2])


if __name__ == "__main__":
    unittest.main()
