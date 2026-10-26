"""A missing freeze commit needs timing evidence in the signed amendment chain."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

from scripts.lib import eval_artifact, eval_level, eval_validation, publication_gate
from scripts.lib import git_common as git
from scripts.lib.eval_integrity import sign_suite, suite_hash
from scripts.tests.post_evals_post_test import FakeGh, PostCase


class SignedFreezeDisclosureTests(PostCase):
    """Test the real post command with a signed suite and an isolated Git repository."""

    def as_v1(self) -> None:
        """Re-create the original signed hash format without changing any retained suite."""
        self.data = self.reload()
        self.data.pop("integrity_version", None)
        self.data["frozen_hash"] = suite_hash(self.data)
        sign_suite(self.data, strict=True)
        self.save()

    def late_fact(self, fake: FakeGh) -> bool | None:
        """Read the computed late-freeze fact from the posted body."""
        facts = eval_artifact.parse_facts(fake.posted[0].splitlines()[1])
        return None if facts is None else facts[1]

    def merge_codes(self, head: str, late: bool) -> list[str]:
        """Read the merge gate against a direct SHA-bound GO comment for this signed suite."""
        data = self.reload()
        summary = git.EvalSummary(
            0, "2", json.dumps(data), facts=eval_artifact.facts_line(2, late, suite_hash(data)[:16])
        )
        with (
            mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
            mock.patch.object(git, "pr_field", return_value=self.base),
            mock.patch.object(eval_level, "pr_changes", return_value=[("A", ["install.py"])]),
        ):
            return [row["code"] for row in publication_gate.eval_level_check("7", head, "", "")]

    def test_merge_refuses_signed_go_without_timing_amendment(self) -> None:
        """A signed GO comment and late fact do not replace the signed timing amendment."""
        head = self.commit("install.py")
        self.suite(head, 2, freeze_disclosure="Original work predates this freeze")
        self.as_v1()
        self.data = self.reload()
        self.data["frozen_sha"] = "e8d4a0103ad70f14171e905a5e0f567b3073337f"
        self.save()
        self.assertIn("freeze_timing_unverified", self.merge_codes(head, True))

    def test_v1_signed_suite_cannot_change_freeze_metadata(self) -> None:
        """Changing only v1 SHA or time must not turn an old freeze into an early one."""
        head = self.commit("install.py")
        frozen = "e8d4a0103ad70f14171e905a5e0f567b3073337f"
        self.suite(head, 2, frozen_at="2026-10-07T00:00:00Z")
        self.as_v1()
        self.data = self.reload()
        self.data["frozen_sha"] = frozen
        self.save()
        token = f"frozen_sha {frozen} frozen_at 2026-10-07T00:00:00Z timing=unverifiable"
        self.assertEqual(self.cli("amend", "E1", token, "author").returncode, 0)
        self.data = self.reload()
        self.data["frozen_sha"] = self.base
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        self.assertIn("freeze_timing_unverified", self.merge_codes(head, False))
        self.data["frozen_sha"] = frozen
        self.data["frozen_at"] = "2026-10-08T00:00:00Z"
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)

    def test_negated_timing_text_is_not_an_assertion(self) -> None:
        """The words 'not late' and 'verifiable' cannot clear the timing check."""
        head = self.commit("install.py")
        frozen = "e8d4a0103ad70f14171e905a5e0f567b3073337f"
        self.suite(head, 2, frozen_sha=frozen)
        frozen_at = str(self.reload()["frozen_at"])
        reason = f"frozen_sha {frozen} frozen_at {frozen_at}: freeze is not late and timing is verifiable"
        self.assertEqual(self.cli("amend", "E1", reason, "eval-author").returncode, 0)
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        self.assertIn("freeze_timing_unverified", self.merge_codes(head, True))

    def test_mutable_legacy_timing_fields_do_not_clear_late_freeze(self) -> None:
        """A late justification and legacy amendment do not replace the signed token."""
        head = self.commit("install.py")
        self.suite(head, 2, verification_justification="late freeze")
        self.as_v1()
        self.data = self.reload()
        self.data["frozen_sha"] = head
        self.data["amendments"] = [{"eval": "E1", "why": "late freeze"}]
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        self.assertIn("freeze_timing_unverified", self.merge_codes(head, True))

    def test_normal_early_suite_needs_no_timing_amendment(self) -> None:
        """A signed freeze at the branch base passes without a timing token."""
        head = self.commit("install.py")
        self.suite(head, 2)
        self.assertEqual(self.merge_codes(head, False), [])

    def test_full_sha_required_outside_git_repository(self) -> None:
        """The format rule still applies when no Git worktree is available."""
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "evals.json"
            path.write_text(json.dumps({"verification_level": 2, "frozen_sha": "HEAD"}))
            previous = Path.cwd()
            try:
                os.chdir(scratch)
                with self.assertRaisesRegex(ValueError, "full 40-hex frozen_sha"):
                    eval_validation.validate_freeze(path)
            finally:
                os.chdir(previous)

    def test_missing_c3_freeze_commit_needs_signed_exact_sha_amendment(self) -> None:
        """C3's full freeze SHA is absent; a mutable note cannot replace signed timing evidence."""
        head = self.commit("install.py")
        frozen = "e8d4a0103ad70f14171e905a5e0f567b3073337f"
        disclosure = "Original builds precede this freeze; it is not a before-original-build claim."
        self.suite(head, 2, freeze_disclosure=disclosure)
        self.as_v1()
        self.data = self.reload()
        self.data["frozen_sha"] = frozen
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        self.data = self.reload()
        self.data["freeze_disclosure"] = "late; " + disclosure
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        frozen_at = str(self.data["frozen_at"])
        wrong = self.cli(
            "amend", "E1", f"frozen_sha {'f' * 40} frozen_at {frozen_at} timing=unverifiable", "eval-author"
        )
        self.assertEqual(wrong.returncode, 0, wrong.stderr)
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        vague = self.cli("amend", "E1", f"frozen_sha {frozen} frozen_at {frozen_at} timing=checked", "eval-author")
        self.assertEqual(vague.returncode, 0, vague.stderr)
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        reason = f"frozen_sha {frozen} frozen_at {frozen_at} timing=unverifiable"
        amended = self.cli("amend", "E1", reason, "eval-author")
        self.assertEqual(amended.returncode, 0, amended.stderr)
        with mock.patch.dict(os.environ, {"CODERAILS_KEYS_DIR": str(self.directory / "missing-signers")}):
            self.assertEqual(self.post(FakeGh([head]))[0], 1)
        fake = FakeGh([head])
        code, _, error = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), error)
        self.assertEqual(self.late_fact(fake), True)
        self.assertEqual(self.merge_codes(head, True), [])
        self.data = self.reload()
        self.data["amendment_chain"][-1]["reason"] = "altered after signing"
        self.save()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)

    def test_resolved_late_freeze_accepts_signed_timing_amendment(self) -> None:
        """A branch commit is late even when Git can resolve it; the signed reason can disclose it."""
        head = self.commit("install.py")
        self.suite(head, 2, frozen_sha=head, verification_justification="irreversible surface")
        self.data = self.reload()
        self.assertEqual(self.post(FakeGh([head]))[0], 1)
        frozen_at = str(self.data["frozen_at"])
        amended = self.cli("amend", "E1", f"frozen_sha {head} frozen_at {frozen_at} timing=late", "eval-author")
        self.assertEqual(amended.returncode, 0, amended.stderr)
        fake = FakeGh([head])
        code, _, error = self.post(fake)
        self.assertEqual((code, len(fake.posted)), (0, 1), error)
        self.assertEqual(self.late_fact(fake), True)
        self.assertEqual(self.merge_codes(head, True), [])
