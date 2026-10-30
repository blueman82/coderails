"""Every Codex spawn_agent in a graph-bound session must carry a valid begin-wave envelope."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import loop_dispatch_guard as guard

ENVELOPE = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(
    {
        "envelope_version": 2,
        "dispatch_id": "disp_1",
        "session_id": "parent",
        "loop_id": "loop",
        "revision": 2,
        "wave_id": "wave-2",
        "node_id": "S2",
    }
)


class DispatchFixture(unittest.TestCase):
    """Shared native dispatch fixture; no inherited test cases."""

    def setUp(self) -> None:
        """Create a graph-bound session with one enveloped dispatch."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        graph_root = patch.dict(os.environ, {"CODERAILS_AGENTIC_LOOP_DIR": str(Path(self.scratch.name) / "loops")})
        graph_root.start()
        self.addCleanup(graph_root.stop)
        self.state = Path(self.scratch.name) / "progress.json"
        self.state.touch()
        self.tool_input: dict[str, Any] = {
            "task_name": "loop_worker_6c6f6f70_55335b315d",
            "message": ENVELOPE + "\nsections\nImplement the node.",
        }
        self.payload: dict[str, Any] = {
            "tool_name": "spawn_agent",
            "tool_use_id": "call-spawn",
            "session_id": "parent",
            "cwd": str(self.state.parent),
            "tool_input": self.tool_input,
        }
        self.sent: list[tuple[Any, ...]] = []
        self.message_file_text = ""

    def _run(
        self,
        authorized: bool = True,
        status: str = "in-progress",
        config: Path | None = None,
        inspection_node: str = "S2",
    ) -> tuple[bool, int]:
        """Run the hook; return (denied, authorize calls)."""

        def graph_output(_graph: Path, *arguments: str, timeout_seconds: float | None = None) -> dict[str, Any] | None:
            if arguments[0] == "inspect":
                return {"status": status, "task_names": {inspection_node: self.tool_input["task_name"]}}
            self.sent.append(arguments)
            self.message_file_text = Path(arguments[arguments.index("--message-file") + 1]).read_text()
            return {"loop_id": "loop", "wave_id": "wave-2", "dispatch_id": "disp_1"} if authorized else None

        def state_path(
            _cwd: str, _session: str, *, strict: bool = False, timeout_seconds: float | None = None
        ) -> Path | None:
            return self.state if self.state.is_file() else None

        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "strict_config_path", return_value=str(config) if config else ""),
            patch.object(guard, "loop_state_path", side_effect=state_path),
            patch.object(guard, "graph_path", return_value=Path(guard.__file__)),
            patch.object(guard, "graph_output", side_effect=graph_output),
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
            patch.object(guard, "append_trace_row"),
        ):
            self.assertEqual(guard.main(), 0)
            self.denial_reason = str(denial.call_args.args[0]) if denial.call_args else ""
        return denial.called, len(self.sent)
