"""Ensure current native graph spawns reach the existing dispatch authority."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import loop_dispatch_guard as guard


class DispatchGuardTests(unittest.TestCase):
    """Test graph dispatch routing and fail-closed authority results."""

    def setUp(self) -> None:
        """Create a canonical role-less dispatch and local authority paths."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.state = Path(self.scratch.name) / "progress.json"
        self.state.touch()
        self.task = "loop_worker_55335b315d"
        self.tool_input: dict[str, Any] = {
            "task_name": self.task,
            "message": f"CODERAILS_GRAPH_TASK={self.task}\nImplement the node.",
        }
        self.payload: dict[str, Any] = {
            "tool_name": "spawn_agent",
            "session_id": "parent",
            "cwd": str(self.state.parent),
            "tool_input": self.tool_input,
        }

    def _run(self, authorized: bool = True, denied: bool = False, ordinary: bool = False) -> None:
        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "loop_state_path", return_value=self.state),
            patch.object(guard, "graph_path", return_value=Path(guard.__file__)),
            patch.object(
                guard,
                "graph_output",
                side_effect=[
                    {"status": "in-progress"},
                    {"loop_id": "loop", "wave_id": "wave-1"} if authorized else None,
                ],
            ) as authority,
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
        ):
            self.assertEqual(guard.main(), 0)
            self.assertEqual(denial.called, denied)
            if not denied:
                self.assertEqual(authority.call_count, 0 if ordinary else 2)
            if authority.call_count == 2:
                self.assertEqual(
                    authority.call_args.args[1:],
                    (
                        "authorize-dispatch",
                        str(self.state),
                        "--session",
                        self.payload["session_id"],
                        "--task",
                        self.task,
                        "--evals",
                        str(self.state.parent / "evals.json"),
                    ),
                )
            elif not denied:
                self.assertEqual(authority.call_count, 0)

    def test_roleless_dispatch_reaches_authority(self) -> None:
        """Require the existing active-wave and frozen-eval authority for role-less workers."""
        self._run()
        self._run(authorized=False, denied=True)

    def test_typed_legacy_marker_dispatch_preserved(self) -> None:
        """Preserve typed dispatches whose task was historically carried by the marker."""
        self.tool_input.pop("task_name")
        self.tool_input["agent_type"] = "loop-worker"
        self._run()

    def test_native_role_dispatch_reaches_authority(self) -> None:
        """Native roles do not exempt graph workers from authorization."""
        self.tool_input["agent_type"] = "worker"
        self._run()
        self._run(authorized=False, denied=True)

    def test_invalid_task_marker_role_and_session_rejected(self) -> None:
        """Reject ambiguous task identity and missing dispatch ownership."""
        cases = [
            (self.tool_input, "message", "missing marker"),
            (self.tool_input, "message", "CODERAILS_GRAPH_TASK=loop_worker_41"),
            (self.tool_input, "task_name", "ordinary"),
            (self.tool_input, "task_name", None),
            (self.tool_input, "agent_type", ""),
            (self.tool_input, "agent_type", None),
            (self.payload, "session_id", ""),
            (self.payload, "cwd", ""),
        ]
        for target, key, value in cases:
            with self.subTest(key=key, value=value):
                present, original = key in target, target.get(key)
                target[key] = value
                self._run(denied=True)
                if present:
                    target[key] = original
                else:
                    target.pop(key)

    def test_missing_state_rejected(self) -> None:
        """Do not dispatch a canonical graph task before graph creation."""
        self.state.unlink()
        self._run(denied=True)

    def test_ordinary_task_allowed(self) -> None:
        """Leave unrelated native subagent tasks outside the graph gate."""
        self.tool_input.update(task_name="ordinary", message="Read documentation.")
        self._run(ordinary=True)

    def test_malformed_graph_marker_cannot_be_ordinary(self) -> None:
        """An invalid explicit graph marker must not skip authorization."""
        self.tool_input.update(task_name="ordinary", message="CODERAILS_GRAPH_TASK=invalid")
        self._run(denied=True)


if __name__ == "__main__":
    unittest.main()
