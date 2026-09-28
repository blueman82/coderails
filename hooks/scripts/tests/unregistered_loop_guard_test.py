#!/usr/bin/env python3
"""Keep unregistered native dispatch detection advisory, distinct-turn based, and deduplicated."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from hooks.scripts.unregistered_loop_guard import count_dispatch_turns


class UnregisteredLoopTests(HookTestCase):
    """Exercise native message identity, parsing failure attribution, and advisory suppression."""

    def dispatches(self, count: int, same_message: bool = False, tool: str = "Agent") -> Path:
        """Write native Agent dispatches with controlled message identities."""
        path = self.directory / "transcript.jsonl"
        entries: list[dict[str, Any]] = [
            {
                "type": "assistant",
                "message": {
                    "id": "shared" if same_message else str(index),
                    "content": [{"type": "tool_use", "name": tool, "input": {}}],
                },
            }
            for index in range(count)
        ]
        path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n")
        return path

    def test_distinct_messages_and_fanout(self) -> None:
        """Three turns count three; parallel calls in one turn count one; other tools count zero."""
        for count, same, tool, expected in (
            (3, False, "Agent", 3),
            (5, True, "Agent", 1),
            (3, False, "Task", 0),
            (0, False, "Agent", 0),
        ):
            self.assertEqual(count_dispatch_turns(str(self.dispatches(count, same, tool))), (expected, ""))

    def test_tolerant_lines_and_aggregate_shape_failure(self) -> None:
        """Individual bad lines are skipped, but unreadable aggregates remain attributed fail-open."""
        path = self.dispatches(3)
        original = path.read_text()
        for bad in ("bad\n", '"scalar"\n', "\n\nnot json\n"):
            path.write_text(bad + original)
            self.assertEqual(count_dispatch_turns(str(path)), (3, ""))
        path.write_text(original + '{"type":"assistant","message":"bad"}\n')
        self.assertEqual(count_dispatch_turns(str(path)), (0, "json_parse_error"))
        path.write_text("bad\n")
        self.assertEqual(count_dispatch_turns(str(path)), (0, "json_parse_error"))
        result = self.run_hook("unregistered_loop_guard", self.payload(path))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertIn("reason=json_parse_error", (self.directory / "discipline.log").read_text())

    def test_one_nudge_per_session_with_native_output(self) -> None:
        """Three genuine dispatch turns produce one Stop advisory and never block."""
        payload = self.payload(self.dispatches(3))
        first = self.run_hook("unregistered_loop_guard", payload)
        self.assertEqual(first.returncode, 0)
        output = json.loads(first.stdout)["hookSpecificOutput"]
        self.assertEqual(output["hookEventName"], "Stop")
        self.assertIn("3+ separate Agent turns", output["additionalContext"])
        self.assertEqual(self.run_hook("unregistered_loop_guard", payload).stdout, "")
        payload["session_id"] = "S2"
        self.assertTrue(self.run_hook("unregistered_loop_guard", payload).stdout)

    def test_registered_invoked_and_below_threshold_are_silent(self) -> None:
        """Existing state, prior loop invocation, fanout, and fewer turns avoid nudges."""
        for count, shared in ((2, False), (5, True)):
            result = self.run_hook("unregistered_loop_guard", self.payload(self.dispatches(count, shared)))
            self.assertEqual((result.returncode, result.stdout), (0, ""))
        path = self.dispatches(3)
        state = self.progress()
        self.assertEqual(self.run_hook("unregistered_loop_guard", self.payload(path)).stdout, "")
        state.unlink()
        with path.open("a") as stream:
            stream.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}
                            ]
                        },
                    }
                )
                + "\n"
            )
        self.assertEqual(self.run_hook("unregistered_loop_guard", self.payload(path)).stdout, "")
        self.assertEqual(self.run_hook("unregistered_loop_guard", {}).stdout, "")


if __name__ == "__main__":
    unittest.main()
