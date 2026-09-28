"""Preserve comment-only citation detection and punctuation/string controls."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase


class CitationTests(HookCase):
    """Durable references survive while transient comment citations are denied."""

    def test_citation_families_and_comment_spans(self) -> None:
        """Check every citation family, block-comment form, and apostrophe case."""
        citations = (
            "# E1: trust baseline",
            "// F4 fix: anchor ext",
            "# CHANGE B2: per-PR check",
            "# Task A3 verifies...",
            "# per finding TA-I1",
            "# reviewer finding FH",
            "# eval E2 covers...",
            "# WU5: rewrite target",
            "# (C2, anti-stall) shared with loop guard",
            "# fallback logic...(per F3 design):",
            "# per the plan's step 2",
            "# per the design doc",
            "foo=1  # E1: reviewer finding said guard this",
            "int x; /* E1: reviewer finding */",
            "/* E1: reviewer finding said guard this",
            "const x = 1; /* per the plan */",
            " * per the design doc",
            "// E1: reviewer finding",
            "# don't cite E1: because it isn't resolvable",
            "# it's per the plan, don't change it",
            "msg='E1: pending'",
            "# E1: x # y",
            "// E1: x // y",
        )
        for text in citations:
            with self.subTest(text=text):
                self.assertTrue(
                    self.denied(
                        "comment_citation_gate",
                        {"tool_name": "Edit", "tool_input": {"file_path": "src/example.py", "new_string": text}},
                    )
                )

    def test_surviving_noncomments_and_durable_references(self) -> None:
        """Code, literal data, Markdown, and real PR links are not transient comments."""
        allowed = (
            ("src/example.py", "# Falls back to $PWD when .cwd is absent."),
            ("src/example.py", "# See PR #42 for context"),
            ("README.md", "# E1: trust baseline"),
            ("fixture.py", "WU3=pending"),
            ("src/example.py", '"WU3": "pending"'),
            ("src/example.py", "# priority P0"),
            ("src/example.py", "# priority P1"),
            ("fixture.json", '{"priority":"P0"}'),
            ("src/example.py", "# CHANGE the default timeout"),
            ("fixture.json", '{"evals":[{"id":"E1:","desc":"gate blocks"}]}'),
            ("fixture.py", 'assert_eq "$out" "reviewer finding"'),
            ("src/example.py", 'msg="WU1: pending"'),
        )
        for path, text in allowed:
            self.assertFalse(
                self.denied(
                    "comment_citation_gate",
                    {"tool_name": "Edit", "tool_input": {"file_path": path, "new_string": text}},
                )
            )

    def test_write_multiedit_and_malformed(self) -> None:
        """Inspect all edit members and Write content, while malformed input stands aside."""
        for text, denied in (("# E1: trust baseline", True), ("# Clean, no citation", False)):
            self.assertEqual(
                self.denied(
                    "comment_citation_gate",
                    {"tool_name": "Write", "tool_input": {"file_path": "src/example.py", "content": text}},
                ),
                denied,
            )
        self.assertTrue(
            self.denied(
                "comment_citation_gate",
                {
                    "tool_name": "MultiEdit",
                    "tool_input": {
                        "file_path": "src/example.py",
                        "edits": [{"new_string": "# Clean"}, {"new_string": "# F1 fix: guard"}],
                    },
                },
            )
        )
        for raw in ("", "not valid json {{{"):
            self.assertFalse(self.denied("comment_citation_gate", raw))


if __name__ == "__main__":
    unittest.main()
