"""Keep the trusted attestor boundary narrow and the diff size finite."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gate_policy_test import EvidenceFixture  # type: ignore[import-not-found]
from integrity_policy import gate_pr


class GateEnvelopeTests(unittest.TestCase):
    """Check both sides of the protected source and input size boundaries."""

    def gate(self, client: EvidenceFixture, maximum: int = 524288) -> int:
        """Run the real policy with a local evidence fixture."""
        with redirect_stdout(io.StringIO()):
            return gate_pr(client, 7, maximum, 0)

    def test_unrelated_plugin_paths_can_attest(self) -> None:
        """An ordinary plugin change must remain eligible for review."""
        for filename in (
            "skills/dashboard/page.ts",
            "launchd/job.plist",
            "scripts/merge.py",
            "scripts/lib/eval_artifact.py",
            "hooks/scripts/lib/pr_merge_gate.py",
            "packages/codex/scripts/merge.py",
            "config.schema.json",
        ):
            with self.subTest(filename=filename):
                client = EvidenceFixture()
                client.files = [{"filename": filename}]
                self.assertEqual(self.gate(client), 0)
                self.assertEqual(client.posts[-1][1], "success")

    def test_import_overrides_remain_protected(self) -> None:
        """A package or compiled module can replace a trusted Python import."""
        for filename in (
            "scripts/lib/eval_integrity/__init__.py",
            "scripts/lib/eval_signing.cpython-312-x86_64-linux-gnu.so",
            "scripts/lib/config/__init__.py",
            "scripts/lib/artifact_io/__init__.py",
        ):
            with self.subTest(filename=filename):
                client = EvidenceFixture()
                client.files = [{"filename": filename}]
                self.assertEqual(self.gate(client), 0)
                self.assertEqual(client.posts[-1][1], "failure")
                self.assertNotIn("diff", client.calls)

    def test_diff_boundary_is_inclusive_and_bounded(self) -> None:
        """The gate admits the limit and refuses the next byte."""
        limit = 524288
        prefix = "diff --git a/docs/safe.txt b/docs/safe.txt\n"
        for size, state in ((limit, "success"), (limit + 1, "failure")):
            with self.subTest(size=size):
                client = EvidenceFixture()
                client.diff = prefix + "x" * (size - len(prefix))
                self.assertEqual(self.gate(client, maximum=limit), 0)
                self.assertEqual(client.posts[-1][1], state)


if __name__ == "__main__":
    unittest.main()
