"""Validate legacy and compatibility-line review comment producers."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from packages.codex.scripts.lib.review_artifact import marker as codex_marker
from packages.codex.scripts.post_review import validate_summary as codex_validate
from scripts.lib.review_artifact import marker as claude_marker
from scripts.post_review import validate_summary as claude_validate

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_policy_test import SHA  # type: ignore[import-not-found]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from integrity_evidence import review_valid

MARKER = f"<!-- coderails-review-summary v1 pr=7 head_sha={SHA} -->"
COMPAT = f"<!-- coderails-compat-findings v1 pr=7 head_sha={SHA} count=0 disposition=clean-break -->"
NO_FINDINGS = f"{MARKER}\n{COMPAT}\n## No findings\n"
FINDINGS = "## Critical\nNone\n\n## Important\n- A reviewed issue.\n\n## Suggestions\nNone\n"
CANARY_SHA = "b7bf4b9fa0d6b4514c48fa2677b166ea4b46fa7d"
CANARY_BODY = (
    f"<!-- coderails-review-summary v1 pr=1 head_sha={CANARY_SHA} -->\n"
    f"<!-- coderails-compat-findings v1 pr=1 head_sha={CANARY_SHA} count=0 disposition=clean-break -->\n"
    "## No findings\n"
)


class ReviewCompatTests(unittest.TestCase):
    """The attestor must accept both supported producer formats."""

    def test_both_repo_producers_legacy_no_findings(self) -> None:
        """Both provider helpers currently emit a marker and valid summary."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            for marker, validate in ((claude_marker, claude_validate), (codex_marker, codex_validate)):
                with self.subTest(provider=marker.__module__):
                    for summary in ("## No findings\n", FINDINGS):
                        path.write_text(summary)
                        validate(path)
                        self.assertTrue(review_valid(f"{marker('7', SHA)}\n{summary}", 7, SHA))

    def test_exact_canary_review_comment_shape(self) -> None:
        """The already-posted canary review body stays a valid fixture."""
        self.assertTrue(review_valid(CANARY_BODY, 1, CANARY_SHA))

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
        """A clean-break finding or extra compatibility line cannot pass."""
        preserve_nonzero = COMPAT.replace("count=0 disposition=clean-break", "count=1 disposition=preserve-compat")
        for body in (
            f"{MARKER}\n{COMPAT.replace('count=0', 'count=1')}\n{FINDINGS}",
            f"{MARKER}\n{preserve_nonzero}\n## No findings",
            f"{MARKER}\n{COMPAT}\n{COMPAT}\n## No findings",
            f"{MARKER}\n{COMPAT}\n## No findings\nextra",
        ):
            with self.subTest(body=body):
                self.assertFalse(review_valid(body, 7, SHA))


if __name__ == "__main__":
    unittest.main()
