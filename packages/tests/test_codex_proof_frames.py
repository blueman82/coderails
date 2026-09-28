"""Verify actual desktop exec output framing without accepting ambiguous proof results."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
from graph_artifacts import parse_exec_result


class ProofFrameTests(unittest.TestCase):
    """Native metadata is distinct from the single authoritative result object."""

    def test_actual_completed_desktop_frames(self) -> None:
        """Accept the exact frame shape observed in a real foreground proof execution."""
        payload = {
            "type": "custom_tool_call_output",
            "call_id": "native-call",
            "output": [
                {"type": "input_text", "text": "Script completed\nWall time 4.2 seconds\nOutput:\n"},
                {"type": "input_text", "text": json.dumps({"loop_id": "loop", "exit_code": 0, "output": "5 passed"})},
            ],
        }
        self.assertEqual(parse_exec_result(payload), ("native-call", True, "loop"))

    def test_ambiguous_or_noncompleted_frames_fail_closed(self) -> None:
        """Extra results, arbitrary prefix prose and unfinished scripts cannot prove success."""
        result = {"type": "input_text", "text": '{"exit_code":0,"loop_id":"loop"}'}
        for frames in (
            [result, result],
            [{"type": "input_text", "text": "Script failed\nOutput:\n"}, result],
            [{"type": "input_text", "text": "Script running with cell ID 1"}, result],
            [{"type": "input_text", "text": "A purported successful execution: "}, result],
            [{"type": "image", "text": "Script completed\nWall time 4.2 seconds\nOutput:\n"}, result],
        ):
            with self.subTest(frames=frames):
                self.assertEqual(
                    parse_exec_result({"type": "custom_tool_call_output", "call_id": "call", "output": frames}),
                    ("call", False, None),
                )

    def test_result_types_and_standalone_json(self) -> None:
        """Preserve old JSON-result support and reject bool exits or malformed owner identities."""
        for result, passed in (
            ({"exit_code": 0}, True),
            ({"exit_code": 1}, False),
            ({"exit_code": False}, False),
            ({"exit_code": 0, "loop_id": 123}, False),
        ):
            payload = {"type": "function_call_output", "call_id": "call", "output": json.dumps(result)}
            observed = parse_exec_result(payload)
            self.assertIsNotNone(observed)
            self.assertEqual(observed, ("call", passed, None))


if __name__ == "__main__":
    unittest.main()
