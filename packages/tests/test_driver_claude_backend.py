"""Claude workers use the pinned sandbox launcher and typed terminal output."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib import graph_driver_claude  # noqa: E402
from scripts.sandbox.spawn_sandboxed_worker import DRIVER_SCHEMA  # noqa: E402


class ClaudeBackendTests(unittest.TestCase):
    """Fail closed on a missing sandbox route or structured result."""

    def test_malformed_outcome_types_return_a_coded_failure(self) -> None:
        """External JSON arrays, objects and scalars cannot escape result parsing."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output.jsonl"
            outcomes: tuple[object, ...] = ([], {}, None, True, 1)
            for outcome in outcomes:
                with self.subTest(outcome=outcome):
                    malformed = {"outcome": outcome, "evidence": "inert malformed result", "final_report": None}
                    rows = [
                        {"type": "system", "subtype": "init", "session_id": "S"},
                        {"type": "result", "subtype": "success", "is_error": False, "structured_output": malformed},
                    ]
                    output.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
                    self.assertEqual(
                        graph_driver_claude.result(output, 0),
                        {"outcome": "failed", "evidence": "claude:invalid_final_schema"},
                    )

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
            expected = {
                "outcome": "done",
                "evidence": "PR and tests",
                "final_report": {
                    "claims": [{"text": "Disposable result", "label": "verified", "source": "scratch checkout"}],
                    "did_not_verify": [],
                },
            }
            output.write_text(
                json.dumps({"type": "system", "subtype": "init", "session_id": "S"})
                + "\n"
                + json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": expected})
                + "\n"
            )
            self.assertEqual(graph_driver_claude.result(output, 0), expected)
            self.assertIn("skipped", cast(dict[str, Any], DRIVER_SCHEMA)["properties"]["outcome"]["enum"])
            skipped = {"outcome": "skipped", "evidence": "wiki update is out of scope", "final_report": None}
            output.write_text(
                json.dumps({"type": "system", "subtype": "init", "session_id": "S"})
                + "\n"
                + json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": skipped})
                + "\n"
            )
            self.assertEqual(graph_driver_claude.result(output, 0), skipped)
            status = {
                "status": "NEEDS_DECISION",
                "worker": "w1",
                "summary": "blocked",
                "confidence": "verified",
                "question": "Which?",
                "options": ["a", "b"],
                "recommended": "a",
            }
            self.assertIn("NEEDS_DECISION", cast(dict[str, Any], DRIVER_SCHEMA)["properties"]["outcome"]["enum"])
            typed = {"outcome": "NEEDS_DECISION", "evidence": json.dumps(status), "final_report": None}
            output.write_text(
                json.dumps({"type": "system", "subtype": "init", "session_id": "S"})
                + "\n"
                + json.dumps({"type": "result", "subtype": "success", "is_error": False, "structured_output": typed})
                + "\n"
            )
            self.assertEqual(graph_driver_claude.result(output, 0), status)
            output.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False}) + "\n")
            self.assertEqual(graph_driver_claude.result(output, 0)["outcome"], "failed")
            output.write_text(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}))
            self.assertEqual(graph_driver_claude.result(output, 0)["outcome"], "failed")
            self.assertEqual(graph_driver_claude.result(output, 9)["outcome"], "failed")


if __name__ == "__main__":
    unittest.main()
