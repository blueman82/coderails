"""Both review writers bind the compatibility finding to the paired companion."""

from __future__ import annotations

from typing import cast

from packages.tests.test_codex_review_passes import PostTests, Repo, review_valid
from scripts.lib import review_artifact, review_passes


class CompatPairPostTests(Repo):
    """Run the existing fake GitHub CLI for each provider."""

    touched = "docs/a.md"

    def test_both_provider_clis_copy_compat_line_to_companion(self) -> None:
        """A genuine preserve-compat finding appears in both comments for the same head."""
        summary = "## Critical\nNone\n\n## Important\n- Retained compatibility\n\n## Suggestions\nNone\n"
        finding = self.tmp / "finding.md"
        finding.write_text(summary)
        for provider in ("claude", "codex"):
            with self.subTest(provider=provider):
                result, _, posted = PostTests.post(
                    cast(PostTests, self),
                    "12",
                    "--summary",
                    str(finding),
                    "--compat-count",
                    "1",
                    "--disposition",
                    "preserve-compat",
                    provider=provider,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                compat = review_artifact.compat_line("12", self.sha, 1, "preserve-compat")
                self.assertEqual(posted.read_text().splitlines()[2], compat)
                self.assertIsNotNone(review_passes.parse(posted.read_text(), "12", self.sha))
                companion = posted.with_name(posted.name + ".companion").read_text()
                self.assertEqual(companion, review_artifact.marker("12", self.sha) + "\n" + compat + "\n" + summary)
                self.assertTrue(review_valid(companion, 12, self.sha))
