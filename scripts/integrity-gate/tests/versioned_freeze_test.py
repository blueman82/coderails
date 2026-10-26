"""Trusted Actions checks versioned freeze metadata without running PR code."""

from __future__ import annotations

import copy
import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from gate_policy_test import FIXTURE_KEYS, SHA, EvidenceFixture  # type: ignore[import-not-found]
from integrity_policy import gate_pr

from scripts.lib.eval_integrity import append_amendment


class VersionedFreezeTests(unittest.TestCase):
    """Exercise the production attestor against direct owner comments."""

    def gate(self, client: EvidenceFixture) -> int:
        """Run one exact-head attestation without printing routine diagnostics."""
        with redirect_stdout(io.StringIO()):
            return gate_pr(client, 7, 204800, 720)

    def test_v1_direct_comment_without_signed_metadata_is_refused(self) -> None:
        """A GO comment with an old hash cannot attest mutable freeze metadata."""
        client = EvidenceFixture()
        client.document.pop("integrity_version")
        client.resign()
        self.assertEqual(self.gate(client), 1)
        self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_v1_signed_metadata_is_bound_to_sha_and_time(self) -> None:
        """A signed v1 token permits the original format; changing either field then refuses."""
        client = EvidenceFixture()
        client.document.pop("integrity_version")
        client.resign()
        token = (
            f"frozen_sha {client.document['frozen_sha']} frozen_at {client.document['frozen_at']} "
            "timing=unverifiable"
        )
        with patch.dict(os.environ, {"CODERAILS_KEYS_DIR": FIXTURE_KEYS.name}):
            append_amendment(client.document, "E1", token, "fixture")
        self.assertEqual(self.gate(client), 0)
        for key, value in (("frozen_sha", "b" * 40), ("frozen_at", "2026-10-25T00:00:00Z")):
            altered = EvidenceFixture()
            altered.document = copy.deepcopy(client.document)
            altered.document[key] = value
            self.assertEqual(self.gate(altered), 1)
            self.assertIn("eval_evidence_invalid", altered.posts[-1][2])

    def test_v2_freeze_metadata_tamper_is_refused(self) -> None:
        """A direct comment cannot change only a v2 SHA or timestamp after signing."""
        for key, value in (("frozen_sha", "b" * 40), ("frozen_at", "2026-10-25T00:00:00Z")):
            client = EvidenceFixture()
            client.document[key] = value
            self.assertEqual(self.gate(client), 1)
            self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_tampered_frozen_oracle_cannot_attest(self) -> None:
        """A changed oracle must fail its frozen hash check."""
        client = EvidenceFixture()
        client.document["evals"][0]["assert"] = "Changed after the freeze."
        self.assertEqual(self.gate(client), 1)
        self.assertIn("eval_evidence_invalid", client.posts[-1][2])

    def test_negative_grading_chain_length_replaces_old_success(self) -> None:
        """Bad owner grading data must post a newer error on the same head."""
        for length in (-1, -2):
            with self.subTest(chain_len=length):
                client = EvidenceFixture()
                client.statuses = [{"context": "integrity-review", "state": "success"}]
                client.document["grading"] = {"chain_len": length}
                self.assertEqual((self.gate(client), client.posts[-1][:2]), (1, (SHA, "error")))
                self.assertIn("eval_evidence_invalid", client.posts[-1][2])
