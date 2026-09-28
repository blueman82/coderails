"""Preserve review grammar, cache atomicity and concurrent progress updates."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_state_common import atomic_progress_update
from scripts import post_review


class WorkflowReviewTests(unittest.TestCase):
    """Require meaningful summaries and retain all unrelated locked progress state."""

    def test_summary_grammar_and_cli_exit(self) -> None:
        """Reject missing, hollow and ambiguous summaries with exit one."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            path = Path(temporary) / "summary"
            self.assertEqual(post_review.main(["validate", str(path)]), 1)
            self.assertEqual(post_review.main([]), 1)
            for text in (
                "## No findings\n",
                "## Critical\n- a\n## Important\n- b\n## Suggestions\n- c\n",
                "## Critical\nNone\n## Important\nNone\n## Suggestions\nNone\n",
            ):
                path.write_text(text)
                self.assertEqual(post_review.main(["validate", str(path)]), 0)
            for text in (
                "review done\n",
                "## Critical\n## Important\nNone\n## Suggestions\nNone\n",
                "## Critical\nNone\n## Important\nNone\n",
                "## No findings\n## Critical\nNone\n",
            ):
                path.write_text(text)
                self.assertEqual(post_review.main(["validate", str(path)]), 1)

    def test_absent_corrupt_and_full_cache(self) -> None:
        """Skip absent state, refuse malformed state, and populate every cache field."""
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stderr(io.StringIO()):
            path = Path(temporary) / "progress.json"
            self.assertEqual(post_review.write_cache(path, "42", "sha", "url", "author", "time"), 0)
            self.assertFalse(path.exists())
            path.write_text("malformed")
            self.assertEqual(post_review.write_cache(path, "42", "sha", "url", "author", "time"), 1)
            self.assertEqual(path.read_text(), "malformed")
            self.assertEqual(list(Path(temporary).glob("*.tmp.*")), [])
            path.write_text('{"status":"in-progress","session_id":"session"}')
            self.assertEqual(post_review.write_cache(path, "42", "sha", "url", "author", "time"), 0)
            data = json.loads(path.read_text())
            self.assertEqual(data["status"], "in-progress")
            self.assertEqual(data["session_id"], "session")
            self.assertEqual(
                data["review"],
                {
                    "ran": True,
                    "pr": 42,
                    "head_sha": "sha",
                    "summary_posted": True,
                    "summary_url": "url",
                    "summary_author": "author",
                    "posted_at": "time",
                },
            )

    def test_concurrent_cache_and_counter_survive(self) -> None:
        """Serialize independent mutations through the provider-owned progress lock."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress.json"
            path.write_text('{"counter":0}')

            def increment(data: dict[str, Any]) -> dict[str, Any]:
                """Update the counter from the freshly locked document."""
                data["counter"] += 1
                return data

            with ThreadPoolExecutor(max_workers=2) as executor:
                review = executor.submit(post_review.write_cache, path, "43", "sha", "url", "author", "time")
                counter = executor.submit(atomic_progress_update, path, increment)
                self.assertEqual(review.result(), 0)
                self.assertTrue(counter.result())
            data = json.loads(path.read_text())
            self.assertEqual(data["counter"], 1)
            self.assertEqual(data["review"]["pr"], 43)
            self.assertFalse(Path(str(path) + ".lock").exists())


if __name__ == "__main__":
    unittest.main()
