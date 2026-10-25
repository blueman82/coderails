"""Every Codex spawn_agent in a graph-bound session must carry a valid begin-wave envelope."""

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


class DispatchGuardTests(unittest.TestCase):
    """Test graph dispatch routing and fail-closed authority results."""

    def setUp(self) -> None:
        """Create a graph-bound session with one enveloped dispatch."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
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
        self, authorized: bool = True, status: str = "in-progress", config: Path | None = None
    ) -> tuple[bool, int]:
        """Run the hook; return (denied, authorize calls)."""

        def graph_output(_graph: Path, *arguments: str) -> dict[str, Any] | None:
            if arguments[0] == "inspect":
                return {"status": status}
            self.sent.append(arguments)
            self.message_file_text = Path(arguments[arguments.index("--message-file") + 1]).read_text()
            return {"loop_id": "loop", "wave_id": "wave-2", "dispatch_id": "disp_1"} if authorized else None

        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "config_path", return_value=str(config) if config else "", create=True),
            patch.object(guard, "loop_state_path", return_value=self.state),
            patch.object(guard, "graph_path", return_value=Path(guard.__file__)),
            patch.object(guard, "graph_output", side_effect=graph_output),
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
            patch.object(guard, "append_trace_row"),
        ):
            self.assertEqual(guard.main(), 0)
        return denial.called, len(self.sent)

    def test_invalid_typed_config_blocks_native_worker_dispatch(self) -> None:
        """A misspelled sandbox control cannot reach Codex's actual spawn gate."""
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workerz: true\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (True, 0))

    def test_valid_default_sandbox_setting_preserves_scout_dispatch(self) -> None:
        """The containment rule applies to implementation work, not scout dispatch."""
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workers: true\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (False, 1))

    def test_default_containment_refuses_native_implementation(self) -> None:
        """Native implementation inherits the parent sandbox and must not bypass the separate process."""
        self.tool_input["message"] = self.tool_input["message"].replace('"S2"', '"U3[1]"')
        self.assertEqual(self._run(), (True, 0))

    def test_explicit_containment_off_allows_native_implementation(self) -> None:
        """The owner can make the documented opt-out in the workflow config."""
        self.tool_input["message"] = self.tool_input["message"].replace('"S2"', '"U3[1]"')
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workers: false\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (False, 1))

    def test_roleless_dispatch_reaches_authority(self) -> None:
        """Require the existing active-wave and frozen-eval authority for role-less workers."""
        self.assertEqual(self._run(), (False, 1))
        self.assertEqual(self._run(authorized=False), (True, 2))

    def test_hook_no_longer_recognizes_graph_work_by_name(self) -> None:
        """Neither the task-name regex nor the first-line task marker survives in the hook."""
        source = Path(guard.__file__).read_text()
        self.assertNotIn("TASK_NAME", source)
        self.assertNotIn("CODERAILS_GRAPH_TASK", source)

    def test_enveloped_dispatch_reaches_authority_with_the_message_in_a_file(self) -> None:
        """The CLI receives the dispatch id, a file holding the exact message, the agent type and task name."""
        self.assertEqual(self._run(), (False, 1))
        arguments = self.sent[0]
        self.assertEqual(
            [arguments[i] for i in (0, 1, 2, 3, 4, 5, 8, 9, 10, 11)],
            [
                "authorize-dispatch",
                str(self.state),
                "--session",
                "parent",
                "--dispatch-id",
                "disp_1",
                "--agent-type",
                "",
                "--task-name",
                self.tool_input["task_name"],
            ],
        )
        self.assertEqual(self.message_file_text, self.tool_input["message"])
        self.assertEqual(self.sent[0][-2:], ("--tool-use-id", "call-spawn"))

    def test_graph_spawn_without_native_call_id_is_denied(self) -> None:
        """An opaque transcript cannot be joined to a hook approval without the native call id."""
        del self.payload["tool_use_id"]
        self.assertEqual(self._run(), (True, 0))

    def test_arbitrary_task_name_without_an_envelope_is_denied(self) -> None:
        """The old regex let any non-graph-looking spawn through; in a graph-bound session it is now denied."""
        self.tool_input.update(task_name="ordinary", message="Read documentation.")
        self.assertEqual(self._run(authorized=False), (True, 1))
        self.assertEqual(self.sent[0][arguments_index(self.sent[0], "--dispatch-id")], "")

    def test_authority_refusal_denies(self) -> None:
        """A refusal by the graph CLI denies the spawn, with or without a native role."""
        self.assertEqual(self._run(authorized=False), (True, 1))
        self.tool_input["agent_type"] = "worker"
        self.assertEqual(self._run(authorized=False), (True, 2))
        self.assertEqual(self.sent[1][arguments_index(self.sent[1], "--agent-type")], "worker")

    def test_blank_or_malformed_native_role_denied_before_authority(self) -> None:
        """A supplied agent_type must be a nonblank string."""
        for value in ("", "  ", None, 3):
            with self.subTest(value=value):
                self.tool_input["agent_type"] = value
                self.assertEqual(self._run(), (True, 0))

    def test_no_progress_file_means_no_graph_binding(self) -> None:
        """A session without a loop may spawn freely; a dispatch envelope without state is denied."""
        self.state.unlink()
        self.tool_input.update(task_name="ordinary", message="Read documentation.")
        self.assertEqual(self._run(), (False, 0))
        self.tool_input["message"] = ENVELOPE + "\nx"
        self.assertEqual(self._run(), (True, 0))

    def test_completed_graph_allows_ordinary_spawns_but_not_dispatches(self) -> None:
        """A finished loop does not bind unrelated agents, and cannot dispatch graph workers."""
        self.tool_input.update(task_name="ordinary", message="Read documentation.")
        self.assertEqual(self._run(status="complete"), (False, 0))
        self.tool_input["message"] = ENVELOPE + "\nx"
        self.assertEqual(self._run(status="complete"), (True, 0))

    def test_missing_identity_denies_only_enveloped_dispatch(self) -> None:
        """Without a session id the hook cannot bind a spawn, but it will not authorize an envelope blind."""
        self.payload["session_id"] = ""
        self.assertEqual(self._run(), (True, 0))
        self.tool_input["message"] = "Read documentation."
        self.assertEqual(self._run(), (False, 0))

    def test_other_tools_denied(self) -> None:
        """Codex graph workers use native spawn_agent only."""
        self.payload["tool_name"] = "Agent"
        self.assertEqual(self._run(), (True, 0))


def arguments_index(arguments: tuple[Any, ...], name: str) -> int:
    """Position of the value following a named option."""
    return arguments.index(name) + 1


if __name__ == "__main__":
    unittest.main()
