"""Codex workers use a private home and require terminal structured output."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"
sys.path.insert(0, str(SCRIPTS))
import graph_driver_codex  # noqa: E402


class CodexBackendTests(unittest.TestCase):
    """Check the current OAuth CLI route and strict evidence parser."""

    def test_command_uses_codex_exec_and_current_login(self) -> None:
        """The worker uses the existing Codex login with explicit result controls."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            prompt = artifact / "prompt.txt"
            prompt.write_text("owned prompt\n")
            argv, environment, stdin_path = graph_driver_codex.command(prompt, artifact, cli="/fake/codex")
            self.assertEqual(argv[0], "/fake/codex")
            self.assertEqual(argv[1], "exec")
            self.assertIn("--json", argv)
            self.assertIn("--output-schema", argv)
            self.assertIn("--output-last-message", argv)
            self.assertIn("workspace-write", argv)
            self.assertIn("features.multi_agent=false", argv)
            self.assertEqual(stdin_path, prompt)
            self.assertIsNone(environment)
            self.assertNotIn("--ignore-user-config", argv)

    def test_result_requires_successful_terminal_event_and_closed_json(self) -> None:
        """An exit code or plausible prose cannot stand in for completed structured output."""
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory)
            output = artifact / "output.jsonl"
            final = artifact / "final.json"
            expected = {
                "outcome": "done",
                "evidence": "PR and test details",
                "final_report": {
                    "claims": [{"text": "Disposable result", "label": "verified", "source": "scratch checkout"}],
                    "did_not_verify": [],
                },
            }
            valid = (
                '{"type":"thread.started","thread_id":"T"}\n'
                + json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(expected)}}
                )
                + '\n{"type":"turn.completed"}\n'
            )
            output.write_text(valid)
            final.write_text(json.dumps(expected))
            self.assertEqual(graph_driver_codex.result(output, 0), expected)
            output.write_text('{"type":"thread.started","thread_id":"T"}\n')
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            output.write_text('{"type":"turn.failed"}\n')
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            output.write_text(valid)
            final.write_text('{"outcome":"done","evidence":"x","extra":true}')
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            final.write_text(json.dumps({"outcome": "done", "evidence": "different"}))
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")
            final.write_text(json.dumps(expected))
            self.assertEqual(graph_driver_codex.result(output, 7)["outcome"], "failed")
            output.write_text(
                valid.replace(
                    '{"type":"turn.completed"}',
                    '{"type":"item.completed","item":{"type":"collab_tool_call"}}\n{"type":"turn.completed"}',
                )
            )
            self.assertEqual(graph_driver_codex.result(output, 0)["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
