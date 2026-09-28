#!/usr/bin/env python3
"""Pin file-read posting, exact-PR review arguments, and render-time argument safety in workflow docs."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class PostReviewCommandTests(unittest.TestCase):
    """Documentation may instruct execution only after explicit argument inspection."""

    def test_post_review_prerequisites_and_posting_contract(self) -> None:
        """The complete original post-review documentation contract remains enforceable."""
        post = (ROOT / "commands/post-review.md").read_text()
        workflow = (ROOT / "commands/workflow.md").read_text()
        for phrase in (
            "-F body=@",
            "select(. != null)",
            "## Step 0",
            "- Open PRs: !`gh pr list --state open --limit 10`",
        ):
            self.assertIn(phrase, post)
        self.assertNotIn("-f body=@", post)
        self.assertLess(post.index("## Step 0"), post.index("## Step 1"))
        self.assertNotIn("`/pr-review-toolkit:review-pr all`", workflow)
        self.assertIn("/pr-review-toolkit:review-pr <PR#>", workflow)
        for path in (ROOT / "commands").glob("*.md"):
            self.assertIsNone(re.search(r"!`[^`]*\$ARGUMENTS[^`]*`", path.read_text()), str(path))


if __name__ == "__main__":
    unittest.main()
