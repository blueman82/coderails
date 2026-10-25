"""The Codex Stop hook spends one bounded graph-check budget."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "codex/hooks/scripts"
sys.path.insert(0, str(SCRIPTS))
import graph_completion_guard as guard  # noqa: E402
import hook_common  # noqa: E402


class StopBudgetTests(unittest.TestCase):
    """Each subprocess gets only the time left from the same deadline."""

    def setUp(self) -> None:
        """Create one owned state file for each test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / "progress.json"
        self.state.write_text("{}", encoding="utf-8")
        self.payload = {"session_id": "s", "cwd": temporary.name}

    def run_guard(self, graph: object) -> dict[str, object]:
        """Run main with a real response envelope and fake graph paths."""
        output = io.StringIO()
        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "loop_state_path", return_value=self.state),
            patch.object(guard, "graph_path", return_value=Path("graph.py")),
            patch.object(guard, "graph_output", side_effect=graph),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(guard.main(), 0)
        return cast(dict[str, object], json.loads(output.getvalue()))

    def test_inspect_consume_and_verify_use_one_deadline(self) -> None:
        """Later graph calls cannot restart the ten-second Stop allowance."""
        timeouts: list[float] = []

        def graph(_path: Path, command: str, *_args: str, timeout_seconds: float) -> object:
            timeouts.append(timeout_seconds)
            return {"session_id": "s"} if command == "inspect" else None

        with patch("graph_completion_guard.time.monotonic", side_effect=[0.0, 1.0, 2.0, 3.0, 4.0]):
            response = self.run_guard(graph)
        self.assertEqual(timeouts, [7.0, 6.0, 5.0])
        self.assertEqual(response["decision"], "block")

    def test_graph_timeout_is_a_retryable_block(self) -> None:
        """A timed-out inspect must not become an invalid-state claim."""
        response = self.run_guard(hook_common.GraphTimeoutError("expired"))
        self.assertEqual(response["decision"], "block")
        self.assertIn("timed out", str(response["reason"]))
        self.assertNotIn("invalid", str(response["reason"]))

    def test_approval_status_uses_the_original_deadline(self) -> None:
        """The notice and recovery path cannot start a new four-second budget."""
        captured: list[float | None] = []

        def notice(*_args: object, deadline: float | None = None) -> str:
            captured.append(deadline)
            return "status"

        def graph(_path: Path, command: str, *_args: str, timeout_seconds: float) -> object:
            return {"session_id": "s", "loop_id": "l", "revision": 1} if command == "inspect" else None

        with (
            patch("graph_completion_guard.time.monotonic", side_effect=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0]),
            patch.object(guard, "unresolved", return_value=True),
            patch.object(guard, "status_notice", side_effect=notice),
            patch.object(guard, "seen", return_value=False),
            patch.object(guard, "record_notice"),
        ):
            response = self.run_guard(graph)
        self.assertEqual(captured, [9.0])
        self.assertIn("status", str(response["reason"]))

    def test_subprocess_timeout_is_typed_and_bounded(self) -> None:
        """The graph subprocess receives the remaining time and reports a timeout distinctly."""
        failure = subprocess.TimeoutExpired(["python3", "graph.py"], 0.1)
        with (
            patch("hook_common.subprocess.run", side_effect=failure) as run,
            self.assertRaises(hook_common.GraphTimeoutError),
        ):
            hook_common.graph_output(Path("graph.py"), "inspect", timeout_seconds=0.1)
        self.assertEqual(run.call_args.kwargs["timeout"], 0.1)

    def test_expired_status_does_not_suppress_the_next_recovery(self) -> None:
        """A notice that skipped status work cannot start a 900-second dedupe lease."""
        output = io.StringIO()
        inspection: dict[str, object] = {"loop_id": "l", "revision": 1, "active_wave": None, "hard_stop": None}
        with (
            patch.object(guard, "seen", return_value=False),
            patch.object(guard, "status_notice", return_value="Graph status unavailable: status deadline reached"),
            patch.object(guard, "record_notice") as record,
            patch("graph_completion_guard.time.monotonic", return_value=10.0),
            contextlib.redirect_stdout(output),
        ):
            guard.request_human_approval(self.state, "s", inspection, deadline=9.0)
        self.assertEqual(json.loads(output.getvalue())["decision"], "block")
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
