"""Preserve all wiki-debt coverage, fail-closed and in-progress ingest controls."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.git_common_sync_test import git
from hooks.scripts.tests.workflow_wiki_fixture import WikiFixture


class WikiDebtTests(unittest.TestCase):
    """Use only local vaults and mock GitHub lists, retaining real Git grep/fetch."""

    def test_coverage_grammar_and_repo_boundaries(self) -> None:
        """Accept canonical no-op/origin coverage without matching other repos or PR suffixes."""
        cases = (
            ("## [2026-07-16] no-op | test-repo PR #85 — fixture", False, True),
            ('origin: "test-repo PRs #85, #86"', True, True),
            ('origin: "test-repo PR #85"', True, True),
            ("## [2026-07-16] no-op | test-repo PR #850 — fixture", False, False),
            ("## [2026-07-16] no-op | other-repo PR #85 — fixture", False, False),
            ("mentioned ## [2026-07-16] no-op | test-repo PR #85", False, False),
            ('origin: "xtest-repo PR #85"', True, False),
        )
        for text, source, expected in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                fixture = WikiFixture(Path(directory))
                fixture.coverage(text, source=source)
                accepted, detail = fixture.gate()
                self.assertEqual(accepted, expected, detail)
                if not expected:
                    self.assertIn("#85", detail)
                    self.assertIn("no-op", detail)
        for covered in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                fixture = WikiFixture(Path(directory))
                fixture.repository = "my.repo"
                name = "my.repo" if covered else "myXrepo"
                fixture.coverage(f'origin: "{name} PR #85"', source=True)
                self.assertEqual(fixture.gate()[0], covered)

    def test_inert_epoch_exclusion_and_quoted_config(self) -> None:
        """Skip absent configuration, exclude old/current PRs, and parse quoted scalars."""
        with tempfile.TemporaryDirectory() as directory:
            fixture = WikiFixture(Path(directory))
            for config in ("wiki_path: ../vault\n", "wiki_debt_epoch_pr: 80\n"):
                fixture.configure(config)
                accepted, text = fixture.gate()
                self.assertTrue(accepted)
                self.assertIn("skipped", text)
            fixture.configure()
            fixture.merged = [42, 79, 80]
            self.assertTrue(fixture.gate()[0])
            fixture.merged = [81]
            self.assertTrue(fixture.gate("81")[0])
            fixture.configure('wiki_debt_epoch_pr: "80" # epoch\nwiki_path: "../vault" # vault\n')
            fixture.coverage("## [2026-07-16] no-op | test-repo PR #81 — fixture")
            self.assertTrue(fixture.gate()[0])

    def test_failures_never_demote_to_no_debt(self) -> None:
        """Refuse fetch/shape/window/config failures with distinct actionable diagnostics."""
        with tempfile.TemporaryDirectory() as directory:
            fixture = WikiFixture(Path(directory))
            for mode, expected in (
                ("merged-fail", "GitHub fetch failed"),
                ("fetch-fail", "Wiki fetch failed"),
                ("empty-merged", "empty merged-PR response"),
                ("open-fail", "GitHub fetch failed"),
            ):
                fixture.mode = mode
                accepted, text = fixture.gate()
                self.assertFalse(accepted)
                self.assertIn(expected, text)
            fixture.mode = ""
            fixture.merged = [1] * 100
            self.assertIn("merged-PR window full", fixture.gate()[1])
            fixture.merged = [85]
            fixture.repository = ""
            self.assertIn("Could not resolve the origin repo", fixture.gate()[1])
            fixture.repository = "test-repo"
            fixture.configure("wiki_debt_epoch_pr: 80\nwiki_path: ../absent\n")
            self.assertIn("does not resolve", fixture.gate()[1])
            fixture.configure()
            fixture.mode = "fetch-noop"
            git(fixture.vault, "update-ref", "-d", "refs/remotes/origin/main")
            self.assertIn("no origin/main ref", fixture.gate()[1])
            fixture.config.chmod(0)
            try:
                self.assertIn("Could not read", fixture.gate()[1])
            finally:
                fixture.config.chmod(0o600)

    def test_open_ingest_requires_actual_coverage_and_fetchable_head(self) -> None:
        """Only a covering open PR clears debt; failures stay distinct from uncovered work."""
        for mode in ("covered", "uncovered", "unfetchable"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                fixture = WikiFixture(Path(directory))
                if mode != "unfetchable":
                    text = (
                        "## [2026-07-16] no-op | test-repo PR #85 — fixture" if mode == "covered" else "unrelated work"
                    )
                    fixture.coverage(text, branch="ingest")
                fixture.open_heads = ["ingest"]
                accepted, text = fixture.gate()
                self.assertEqual(accepted, mode == "covered", text)
                if mode == "unfetchable":
                    self.assertIn("could not verify", text)
                elif mode == "uncovered":
                    self.assertIn("#85", text)


if __name__ == "__main__":
    unittest.main()
