"""Real Git replacement refs cannot hide bytes from the trusted import boundary."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests import sandbox_launcher_test as fixture
from hooks.scripts.tests.receipt_test_support import git
from scripts.sandbox import spawn_sandboxed_worker


class ReplacementObjectTests(unittest.TestCase):
    """Reuse the inert launcher fixture with private HOME and a local bare origin."""

    def setUp(self) -> None:
        """Create the same safe fake-worker boundary without running a provider."""
        self.case = fixture.LauncherFlowTests()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_replaced_commit_cannot_hide_out_of_manifest_history(self) -> None:
        """A benign replacement cannot authorize the original raw commit for import."""
        before, pushed = self.case.refs(self.case.primary), git(self.case.origin, "for-each-ref", "refs/heads")

        def worker(clone: Path) -> None:
            parent = git(clone, "rev-parse", "HEAD")
            (clone / "escape.txt").write_text("outside the worker manifest")
            git(clone, "add", "escape.txt")
            git(clone, "commit", "-q", "-m", "outside")
            malicious = git(clone, "rev-parse", "HEAD")
            benign = git(clone, "commit-tree", f"{parent}^{{tree}}", "-p", parent, "-m", "benign")
            git(clone, "replace", malicious, benign)
            self.assertEqual(git(clone, "diff", "--name-only", parent, malicious), "")
            self.assertEqual(git(clone, "--no-replace-objects", "diff", "--name-only", parent, malicious), "escape.txt")

        with (
            patch.object(spawn_sandboxed_worker, "declared_manifest", return_value=["allowed.txt"]),
            self.assertRaisesRegex(ValueError, "branch_import_refused.*out_of_manifest"),
        ):
            self.case.run_launcher(worker)
        self.assertEqual(self.case.refs(self.case.primary), before)
        self.assertEqual(git(self.case.origin, "for-each-ref", "refs/heads"), pushed)

    def test_replaced_blob_cannot_hide_committed_credential(self) -> None:
        """Object byte inspection must ignore replacement blobs as well as commits."""
        before, pushed = self.case.refs(self.case.primary), git(self.case.origin, "for-each-ref", "refs/heads")

        def worker(clone: Path) -> None:
            (clone / "leak.txt").write_text("sk-worker")
            git(clone, "add", "leak.txt")
            git(clone, "commit", "-q", "-m", "secret")
            malicious = git(clone, "rev-parse", "HEAD:leak.txt")
            (clone / "benign.txt").write_text("safe")
            benign = git(clone, "hash-object", "-w", "benign.txt")
            git(clone, "replace", malicious, benign)
            self.assertEqual(git(clone, "cat-file", "-p", malicious), "safe")
            self.assertEqual(git(clone, "--no-replace-objects", "cat-file", "-p", malicious), "sk-worker")

        with self.assertRaisesRegex(ValueError, "branch_import_refused.*secret"):
            self.case.run_launcher(worker)
        self.assertEqual(self.case.refs(self.case.primary), before)
        self.assertEqual(git(self.case.origin, "for-each-ref", "refs/heads"), pushed)

    def test_primary_and_hardened_git_reads_both_use_original_objects(self) -> None:
        """Primary import/merge reads obey the same original-byte rule as clone validation."""
        repo = self.case.primary
        (repo / "original.txt").write_text("original bytes")
        (repo / "replacement.txt").write_text("replacement bytes")
        original = git(repo, "hash-object", "-w", "original.txt")
        replacement = git(repo, "hash-object", "-w", "replacement.txt")
        git(repo, "replace", original, replacement)
        self.assertEqual(git(repo, "cat-file", "-p", original), "replacement bytes")
        for hardened in (False, True):
            with self.subTest(hardened=hardened):
                self.assertEqual(
                    spawn_sandboxed_worker.git(repo, "cat-file", "-p", original, hardened=hardened), "original bytes"
                )


if __name__ == "__main__":
    unittest.main()
