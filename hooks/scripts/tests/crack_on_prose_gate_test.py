"""Preserve prose-question detection, session scope, and bounded Stop retries."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase


class CrackOnProseTests(HookCase):
    """Questions outside code are blocked only while the exact session flag is active."""

    def stop(self, text: str, session: str = "session", active: bool = False, **fields: object) -> dict[str, Any]:
        """Build a native Stop payload pointing at actual JSONL assistant prose."""
        return {
            "hook_event_name": "Stop",
            "session_id": session,
            "transcript_path": str(self.transcript(text)),
            "stop_hook_active": active,
            **fields,
        }

    def test_question_forms(self) -> None:
        """Preserve terminal, modal, decision, and pre-Did-Not-Verify matches."""
        self.assertEqual(self.invoke("crack_on_prose_gate", self.stop("Should I proceed?")).returncode, 0)
        self.flag("session")
        questions = (
            "I compared both hooks. Should I proceed with option A or option B?",
            "The gate only covers the tool. Want me to verify that against the actual hook config?",
            "Both designs are written up above. Let me know which option you prefer.",
            "The migration is staged. Do you want me to run it now or park it.",
            "A uses the counter, B uses stop_hook_active. Which would you prefer?",
            "Should I flip the flag to default-on?\n\n## Did Not Verify\n- rollout preference",
            'Two candidates survived review.\nShall I merge the first one?"',
            "Both PRs are green and parked. Awaiting your decision on the merge order.",
        )
        for text in questions:
            result = self.invoke("crack_on_prose_gate", self.stop(text))
            self.assertEqual(result.returncode, 2, text)
            self.assertIn("[crack-on-block]", result.stderr)
        self.assertRegex(
            self.log.read_text(encoding="utf-8"), r"hook=crack_on_prose_gate .*session=session .*blocked=1"
        )

    def test_declarative_and_quoted_controls(self) -> None:
        """Self-answered prose and fenced, inline, or block-quoted questions survive."""
        self.flag("session")
        allowed = (
            "I built the gate, wired hooks.json, and all 45 tests pass. (verified)",
            "Should I have used a regex here? No — a regex cannot enumerate "
            "variable names, so the gate keys on position instead. Fix shipped and verified.",
            "The fixture asserts the deny text:\n```\nShould I proceed?\n```\nAll suites green.",
            "The eval prompt is frozen verbatim below.\n```\nWhich option do you want?\n```",
            "The deny reason is `should I proceed?` verbatim. Shipped and logged.",
            "> Should I proceed with A or B?\nThat was the question the old gate missed. The new gate catches it.",
            "Merged PR #1, evals GO. (verified)\n\n## Did Not Verify\n- prod timing\n\n"
            "LOOP-STOP: complete — all units shipped",
            "The reviewer asked: is the counter turn-scoped? It is — the reset keys on "
            "stop_hook_active.\nEverything is merged and green.",
        )
        for text in allowed:
            self.assertEqual(self.invoke("crack_on_prose_gate", self.stop(text)).returncode, 0, text)
        self.assertEqual(
            self.invoke("crack_on_prose_gate", self.stop("Should I proceed?", session="elsewhere")).returncode, 0
        )

    def test_counter_cap_reset_and_failure(self) -> None:
        """Keep three blocks per turn, reset on a new turn, and fail open on write failure."""
        directory = self.flag("session")
        for active, expected in ((False, 2), (True, 2), (True, 2), (True, 0), (False, 2)):
            self.assertEqual(
                self.invoke("crack_on_prose_gate", self.stop("Should I proceed?", active=active)).returncode, expected
            )
        self.assertEqual((directory / "prose_question_blocks").read_text(encoding="utf-8").strip(), "1")
        self.assertIn("capped=1", self.log.read_text(encoding="utf-8"))
        bad = self.flag("bad") / "prose_question_blocks"
        bad.mkdir()
        self.assertEqual(
            self.invoke("crack_on_prose_gate", self.stop("Should I proceed?", session="bad")).returncode, 0
        )
        self.assertIn("err=count_write_failed", self.log.read_text(encoding="utf-8"))

    def test_scope_headless_and_degenerate(self) -> None:
        """Headless and non-Stop events stand aside without affecting worker hooks."""
        self.flag("session")
        request = self.stop("Should I proceed?")
        self.assertEqual(self.invoke("crack_on_prose_gate", request, CODERAILS_HEADLESS_RUN="1").returncode, 0)
        request["hook_event_name"] = "SubagentStop"
        self.assertEqual(self.invoke("crack_on_prose_gate", request).returncode, 0)
        for altered in (
            request | {"hook_event_name": "Stop", "transcript_path": "/does/not/exist"},
            {"hook_event_name": "Stop", "transcript_path": request["transcript_path"]},
            "",
        ):
            self.assertEqual(self.invoke("crack_on_prose_gate", altered).returncode, 0)


if __name__ == "__main__":
    unittest.main()
