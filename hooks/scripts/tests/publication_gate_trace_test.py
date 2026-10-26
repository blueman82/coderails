"""Review-pass refusal traces for early evidence failures."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib import publication_gate
from scripts.lib.git_common import ReviewPasses


class ReviewTraceTests(unittest.TestCase):
    """A missing review artifact must produce its named trace row."""

    def test_missing_review_artifact_has_review_passes_refusal_trace(self) -> None:
        """Record the review-pass refusal before returning the violation."""
        with (
            patch("scripts.lib.publication_gate.config_path", return_value="config"),
            patch("scripts.lib.publication_gate.load_config", return_value=({}, "")),
            patch(
                "scripts.lib.publication_gate.git.review_passes_for_pr", return_value=ReviewPasses(2, None, "missing")
            ),
            patch("scripts.lib.publication_gate.git.repo", return_value="owner/repo"),
            patch("scripts.lib.publication_gate.manifest_policy.trace") as trace,
        ):
            result = publication_gate.review_passes_check("517", "head", "", "")
            self.assertEqual(result[0]["code"], "review_artifact_missing")
            trace.assert_called_with("owner/repo@pr-517", "refused", "review_artifact_missing", command="review-passes")
