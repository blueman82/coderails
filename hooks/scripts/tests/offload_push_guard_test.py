"""Preserve observe-only push offload nudges and per-session deduplication."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase


class OffloadTests(HookCase):
    """Require both a protected push and an offload cue before nudging."""

    def test_text_classification_and_deduplication(self) -> None:
        """Nudge protected pushes once per session, keeping safe suggestions silent."""
        cases = (
            ("Please run git push origin main yourself from your own shell.", True),
            ("I cannot push directly, so run this yourself: ! git -C /some/path push origin main", True),
            ("I pushed to origin main and opened the PR.", False),
            ("Run /coderails:push yourself when you're ready to open the PR.", False),
            ("Run this yourself from your own shell: git push origin hooks/offload-guard", False),
            ("You'll need to run this yourself from your own shell to finish up.", False),
            ("", False),
        )
        for index, (text, expected) in enumerate(cases):
            request = {
                "transcript_path": str(self.transcript(text)),
                "session_id": f"session-{index}",
                "hook_event_name": "Stop",
            }
            output = self.output("offload_push_guard", request)
            self.assertEqual(bool(output.get("hookSpecificOutput", {}).get("additionalContext")), expected)
            self.assertEqual(self.output("offload_push_guard", request), {})
        for session in ("separate-a", "separate-b"):
            request = {
                "hook_event_name": "SubagentStop",
                "session_id": session,
                "last_assistant_message": "Please run git push origin main yourself from your own shell.",
            }
            self.assertTrue(self.output("offload_push_guard", request)["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(
            self.output(
                "offload_push_guard",
                {"transcript_path": "/does/not/exist.jsonl", "session_id": "missing", "hook_event_name": "Stop"},
            ),
            {},
        )


if __name__ == "__main__":
    unittest.main()
