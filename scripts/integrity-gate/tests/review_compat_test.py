"""Validate review comments emitted by the installed post-review helper."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_policy_test import SHA  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_evidence import review_valid

MARKER = f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->"
COMPAT = f"<!-- coderails-compat-findings v1 pr=7 head_sha={SHA} count=0 disposition=clean-break -->"
NO_FINDINGS = f"{MARKER}\n{COMPAT}\n## No findings\n"
FINDINGS = "## Critical\nNone\n\n## Important\n- A reviewed issue.\n\n## Suggestions\nNone\n"


class ReviewCompatTests(unittest.TestCase):
    """The attestor must accept the installed helper's exact artifact shape."""

    def test_installed_helper_no_findings_artifact(self) -> None:
        """The helper's marker, typed line, and summary pass together."""
        self.assertTrue(review_valid(NO_FINDINGS, 7, SHA))

    def test_structured_findings_with_preserved_compat(self) -> None:
        """The local gate permits reported findings under preserve-compat."""
        line = COMPAT.replace("count=0 disposition=clean-break", "count=1 disposition=preserve-compat")
        self.assertTrue(review_valid(f"{MARKER}\n{line}\n{FINDINGS}", 7, SHA))

    def test_wrong_identity_and_malformed_compat_line(self) -> None:
        """The typed line must bind the same PR and exact head."""
        for line in (
            COMPAT.replace("pr=7", "pr=8"),
            COMPAT.replace(SHA, "a" * 40),
            COMPAT.replace("count=0", "count=-1"),
            COMPAT.replace("count=0", "count=bad"),
            COMPAT.replace("count=0", "count=01"),
            COMPAT.replace("clean-break", "unknown"),
        ):
            with self.subTest(line=line):
                self.assertFalse(review_valid(f"{MARKER}\n{line}\n## No findings", 7, SHA))

    def test_refusing_count_and_extra_lines(self) -> None:
        """A clean-break finding, missing line, or extra line cannot pass."""
        preserve_nonzero = COMPAT.replace("count=0 disposition=clean-break", "count=1 disposition=preserve-compat")
        for body in (
            f"{MARKER}\n{COMPAT.replace('count=0', 'count=1')}\n{FINDINGS}",
            f"{MARKER}\n{preserve_nonzero}\n## No findings",
            f"{MARKER}\n## No findings",
            f"{MARKER}\n{COMPAT}\n{COMPAT}\n## No findings",
            f"{MARKER}\n{COMPAT}\n## No findings\nextra",
        ):
            with self.subTest(body=body):
                self.assertFalse(review_valid(body, 7, SHA))


if __name__ == "__main__":
    unittest.main()
