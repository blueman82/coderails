"""Claude workers use the pinned sandbox launcher and typed terminal output."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import graph_driver_claude  # noqa: E402


class ClaudeBackendTests(unittest.TestCase):
    """Fail closed on a missing sandbox route or structured result."""

    def test_command_uses_existing_pinned_launcher(self) -> None:
        """The driver routes through the same sandbox script as native workers."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            prompt = base / "prompt.txt"
            prompt.write_text("owned prompt\n")
            argv, environment, stdin_path = graph_driver_claude.command(prompt, base)
            self.assertEqual(argv[0], sys.executable)
            self.assertEqual(Path(argv[1]).name, "spawn_sandboxed_worker.py")
            self.assertIn("--driver", argv)
            self.assertEqual(environment, None)
            self.assertEqual(stdin_path, prompt)

    def test_result_requires_structured_terminal_success(self) -> None:
        """Prose or an error result cannot finish a graph node."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.jsonl"
            expected = {"outcome": "done", "evidence": "PR and tests"}
            output.write_text(
                json.dumps({"type": "system", "subtype": "init", "session_id": "S"})
                + "\n"
                + json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": expected})
                + "\n"
            )
            self.assertEqual(graph_driver_claude.result(output, 0), expected)
            output.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False}) + "\n")
            self.assertEqual(graph_driver_claude.result(output, 0)["outcome"], "failed")
            output.write_text(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}))
            self.assertEqual(graph_driver_claude.result(output, 0)["outcome"], "failed")
            self.assertEqual(graph_driver_claude.result(output, 9)["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
