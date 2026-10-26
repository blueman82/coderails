"""Every Codex spawn_agent in a graph-bound session must carry a valid begin-wave envelope."""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
import loop_dispatch_guard as guard
from hook_common import loop_state_path

from scripts.lib.config import config_path

ENVELOPE = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(
    {
        "envelope_version": 2,
        "dispatch_id": "disp_1",
        "session_id": "parent",
        "loop_id": "loop",
        "revision": 2,
        "wave_id": "wave-2",
        "node_id": "U3[1]",
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

        def graph_output(_graph: Path, *arguments: str, timeout_seconds: float | None = None) -> dict[str, Any] | None:
            if arguments[0] == "inspect":
                return {"status": status}
            self.sent.append(arguments)
            self.message_file_text = Path(arguments[arguments.index("--message-file") + 1]).read_text()
            return {"loop_id": "loop", "wave_id": "wave-2", "dispatch_id": "disp_1"} if authorized else None

        def state_path(_cwd: str, _session: str, *, strict: bool = False) -> Path | None:
            return self.state if self.state.is_file() else None

        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "config_path", return_value=str(config) if config else "", create=True),
            patch.object(guard, "loop_state_path", side_effect=state_path),
            patch.object(guard, "graph_path", return_value=Path(guard.__file__)),
            patch.object(guard, "graph_output", side_effect=graph_output),
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
        ):
            self.assertEqual(guard.main(), 0)
            self.denial_reason = str(denial.call_args.args[0]) if denial.call_args else ""
        return denial.called, len(self.sent)

    def test_invalid_typed_config_blocks_native_worker_dispatch(self) -> None:
        """A misspelled sandbox control cannot reach Codex's actual spawn gate."""
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workerz: true\n", encoding="utf-8")
        self.assertEqual(self._run(config=config), (True, 0))

    def test_valid_default_sandbox_setting_does_not_claim_a_codex_override(self) -> None:
        """The existing Codex API continues dispatch; its sandbox is inherited from the parent session."""
        config = Path(self.scratch.name) / "workflow.config.yaml"
        config.write_text("sandbox_workers: true\n", encoding="utf-8")
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

    def test_native_collaboration_tool_name_reaches_authority(self) -> None:
        """Codex's automatic hook name routes the same native spawn to graph authorization."""
        self.payload["tool_name"] = "collaborationspawn_agent"
        self.payload["tool_use_id"] = "call_501f6560969348d29d04eeef99cb2650"
        self.assertEqual(self._run(), (False, 1))

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

    def test_message_staging_failure_denies_before_authority(self) -> None:
        """A full or inaccessible scratch directory cannot bypass the graph dispatch check."""
        with patch("loop_dispatch_guard.tempfile.TemporaryDirectory", side_effect=OSError("scratch unavailable")):
            self.assertEqual(self._run(), (True, 0))
        with patch("loop_dispatch_guard.Path.write_text", side_effect=OSError("disk full")):
            self.assertEqual(self._run(), (True, 0))

    def test_deep_envelope_denies_without_unhandled_recursion(self) -> None:
        """Malformed nested JSON must yield an explicit hook denial before graph authorization."""
        self.tool_input["message"] = "CODERAILS_GRAPH_DISPATCH=" + "[" * 2000 + "0" + "]" * 2000
        self.assertEqual(self._run(), (True, 0))
        self.assertIn("reason_code=dispatch_hook_error", self.denial_reason)

    def test_deep_hook_payload_denies_without_unhandled_recursion(self) -> None:
        """The same input limit applies when the outer hook payload is deeply nested."""
        with (
            patch.object(guard, "read_input", return_value="[" * 2000 + "0" + "]" * 2000),
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
        ):
            self.assertEqual(guard.main(), 0)
        self.assertIn("reason_code=dispatch_hook_error", denial.call_args.args[0])

    def test_oversized_plaintext_envelope_denies_before_authority(self) -> None:
        """A huge first line cannot consume unbounded work in the envelope parser."""
        self.tool_input["message"] = 'CODERAILS_GRAPH_DISPATCH={"padding":"' + "x" * 9000 + '"}'
        self.assertEqual(self._run(), (True, 0))
        self.assertIn("reason_code=dispatch_hook_error", self.denial_reason)

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

    def test_strict_discovery_propagates_host_resource_errors(self) -> None:
        """ENFILE cannot make a graph or workflow config look absent to the dispatch hook."""
        failure = OSError(errno.ENFILE, "file table full")
        with patch("hook_common.subprocess.run", side_effect=failure), self.assertRaises(OSError):
            loop_state_path(str(self.state.parent), "parent", strict=True)
        with patch("scripts.lib.config.subprocess.run", side_effect=failure), self.assertRaises(OSError):
            config_path(self.state.parent, strict=True)

    def test_strict_graph_discovery_rejects_ambiguous_fallback(self) -> None:
        """Two sibling graphs for one session are not a proven no-graph state."""
        root = Path(self.scratch.name) / "loops"
        for name in ("a", "b"):
            path = root / name / "parent/progress.json"
            path.parent.mkdir(parents=True)
            path.write_text("{}")
        with patch.dict("os.environ", {"CODERAILS_AGENTIC_LOOP_DIR": str(root)}), self.assertRaises(OSError):
            loop_state_path(str(self.state.parent), "parent", strict=True)

    def test_strict_discovery_propagates_list_and_stat_errors(self) -> None:
        """Directory and candidate-file failures cannot look like proven absence."""
        root = Path(self.scratch.name) / "loops"
        with (
            patch.dict("os.environ", {"CODERAILS_AGENTIC_LOOP_DIR": str(root)}),
            patch.object(Path, "iterdir", side_effect=OSError(errno.ENFILE, "file table full")),
            self.assertRaises(OSError),
        ):
            loop_state_path(str(self.state.parent), "parent", strict=True)
        subprocess.run(["git", "init", "-q", str(self.state.parent)], check=True)
        original_stat = Path.stat

        def stat_candidate(path: Path) -> os.stat_result:
            if path.name == "workflow.config.yaml":
                raise OSError(errno.ENFILE, "file table full")
            return original_stat(path)

        with patch.object(Path, "stat", stat_candidate), self.assertRaises(OSError):
            config_path(self.state.parent, strict=True)

    def test_hook_denies_discovery_error_but_allows_proven_absence(self) -> None:
        """An ordinary spawn is free only after both discovery paths finish without error."""
        self.tool_input.update(task_name="ordinary", message="Read documentation.")
        root = Path(self.scratch.name) / "absent-loops"
        with (
            patch.dict("os.environ", {"CODERAILS_AGENTIC_LOOP_DIR": str(root)}),
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "deny") as denial,
        ):
            self.assertEqual(guard.main(), 0)
            denial.assert_not_called()
        failure = OSError(errno.ENFILE, "file table full")
        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch("scripts.lib.config.subprocess.run", side_effect=failure),
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
        ):
            self.assertEqual(guard.main(), 0)
            self.assertIn("dispatch_hook_error", denial.call_args.args[0])
        with (
            patch.object(guard, "read_input", return_value=json.dumps(self.payload)),
            patch.object(guard, "config_path", return_value=""),
            patch("hook_common.subprocess.run", side_effect=failure),
            patch.object(guard, "deny") as denial,
            patch.object(guard, "log"),
        ):
            self.assertEqual(guard.main(), 0)
            self.assertIn("dispatch_hook_error", denial.call_args.args[0])

    def test_completed_graph_allows_ordinary_spawns_but_not_dispatches(self) -> None:
        """A finished loop does not bind unrelated agents, and cannot dispatch graph workers."""
        self.tool_input.update(task_name="ordinary", message="Read documentation.")
        self.assertEqual(self._run(status="complete"), (False, 0))
        self.tool_input["message"] = ENVELOPE + "\nx"
        self.assertEqual(self._run(status="complete"), (True, 0))

    def test_missing_identity_denies_graph_named_dispatch(self) -> None:
        """Without a session id the hook cannot bind a graph name, even if its prompt is opaque."""
        self.payload["session_id"] = ""
        self.assertEqual(self._run(), (True, 0))
        self.tool_input["message"] = "Read documentation."
        self.assertEqual(self._run(), (True, 0))
        self.tool_input["task_name"] = "ordinary"
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
