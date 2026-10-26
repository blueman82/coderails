"""A missing freeze commit needs timing evidence in the signed amendment chain."""

from __future__ import annotations

import os
from unittest import mock

from scripts.lib import eval_artifact
from scripts.tests.post_evals_post_test import FakeGh, PostCase


class SignedFreezeDisclosureTests(PostCase):
    """Test the real post command with a signed suite and an isolated Git repository."""

    def late_fact(self, fake: FakeGh) -> bool | None:
        """Read the computed late-freeze fact from the posted body."""
        facts = eval_artifact.parse_facts(fake.posted[0].splitlines()[1])
        return None if facts is None else facts[1]

    def test_missing_c3_freeze_commit_needs_signed_exact_sha_amendment(self) -> None:
        """C3's full freeze SHA is absent; a mutable note cannot replace signed timing evidence."""
        head = self.commit("install.py")
        frozen = "e8d4a0103ad70f14171e905a5e0f567b3073337f"
        disclosure = "Original builds precede this freeze; it is not a before-original-build claim."
        self.suite(head, 2, freeze_disclosure=disclosure)
        self.data = self.reload()
        self.data["frozen_sha"] = frozen
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        self.data = self.reload()
        self.data["freeze_disclosure"] = "late; " + disclosure
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        wrong = self.cli("amend", "E1", f"frozen_sha {'f' * 40}: timing is unverifiable", "eval-author")
        self.assertEqual(wrong.returncode, 0, wrong.stderr)
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        vague = self.cli("amend", "E1", f"frozen_sha {frozen}: timing was checked", "eval-author")
        self.assertEqual(vague.returncode, 0, vague.stderr)
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        reason = f"frozen_sha {frozen}: timing is unverifiable; treat this freeze as late"
        amended = self.cli("amend", "E1", reason, "eval-author")
        self.assertEqual(amended.returncode, 0, amended.stderr)
        with mock.patch.dict(os.environ, {"CODERAILS_KEYS_DIR": str(self.directory / "missing-signers")}):
            self.assertEqual(self.post(FakeGh([head]))[0], 1)
        fake = FakeGh([head])
        code, _, error = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), error)
        self.assertEqual(self.late_fact(fake), True)
        self.data = self.reload()
        self.data["amendment_chain"][-1]["reason"] = "altered after signing"
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)

    def test_resolved_late_freeze_accepts_signed_timing_amendment(self) -> None:
        """A branch commit is late even when Git can resolve it; the signed reason can disclose it."""
        head = self.commit("install.py")
        self.suite(head, 2, verification_justification="irreversible surface")
        self.data = self.reload()
        self.data["frozen_sha"] = head
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        amended = self.cli("amend", "E1", f"frozen_sha {head}: late freeze after branch base", "eval-author")
        self.assertEqual(amended.returncode, 0, amended.stderr)
        fake = FakeGh([head])
        code, _, error = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), error)
        self.assertEqual(self.late_fact(fake), True)
