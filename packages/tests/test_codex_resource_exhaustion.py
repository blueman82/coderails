"""Host resource exhaustion must never be reported as invalid graph state."""

from __future__ import annotations

import contextlib
import errno
import io
import json
import sys
import tempfile
import unittest
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from unittest.mock import patch

HOOKS = Path(__file__).resolve().parents[1] / "codex/hooks/scripts"
sys.path.insert(0, str(HOOKS))
import graph_completion_guard  # noqa: E402
import hook_common  # noqa: E402
import loop_dispatch_guard  # noqa: E402


def run_hook(module: ModuleType, payload: Mapping[str, object], **patches: object) -> str:
    """Run a hook main() with patched collaborators and return its stdout."""
    output = io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(module, "read_input", return_value=json.dumps(payload)))
        for name, value in patches.items():
            stack.enter_context(patch.object(module, name, value))
        stack.enter_context(contextlib.redirect_stdout(output))
        cast(Callable[[], int], module.main)()
    return output.getvalue()


class ResourceExhaustionTests(unittest.TestCase):
    """EMFILE-class failures are distinguished from corrupt state at every graph call site."""

    def setUp(self) -> None:
        """Create a fake state file and graph helper path."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / "progress.json"
        self.state.write_text("{}", encoding="utf-8")
        self.graph = Path(temporary.name) / "graph.py"
        self.graph.write_text("", encoding="utf-8")

    def collaborators(self) -> dict[str, Any]:
        """Patch values pointing the hooks at the fake state and helper."""

        def state_path(*_: object) -> Path:
            return self.state

        def graph_path() -> Path:
            return self.graph

        return {"loop_state_path": state_path, "graph_path": graph_path}

    def test_graph_output_separates_resource_errors_from_other_failures(self) -> None:
        """Only resource errnos raise; other launch failures keep the established None."""
        failure = OSError(errno.EMFILE, "Too many open files")
        with patch("subprocess.run", side_effect=failure), self.assertRaises(hook_common.HostResourceError):
            hook_common.graph_output(self.graph, "inspect", str(self.state))
        with patch("subprocess.run", side_effect=OSError(errno.ENOENT, "missing")):
            self.assertIsNone(hook_common.graph_output(self.graph, "inspect", str(self.state)))

    def test_stop_hook_reports_resource_exhaustion_not_invalid_state(self) -> None:
        """Both inspect and verify-completion failures yield the resource message."""
        payload = {"session_id": "s", "cwd": "/x", "last_assistant_message": "done"}
        base = self.collaborators()
        raising = patch.object(
            graph_completion_guard, "graph_output", side_effect=hook_common.HostResourceError(errno.EMFILE, "x")
        )
        with raising:
            reason = json.loads(run_hook(graph_completion_guard, payload, **base))["reason"]
        self.assertIn("not known to be invalid", reason)
        self.assertNotIn("is invalid", reason)
        calls = iter([{"session_id": "s", "hard_stop": None}])

        def second_call(*_: object) -> object:
            try:
                return next(calls)
            except StopIteration:
                raise hook_common.HostResourceError(errno.EMFILE, "x") from None

        with patch.object(graph_completion_guard, "graph_output", side_effect=second_call):
            reason = json.loads(run_hook(graph_completion_guard, payload, **base))["reason"]
        self.assertIn("not known to be invalid", reason)

    def test_dispatch_guard_denies_with_resource_message(self) -> None:
        """A resource failure denies dispatch without blaming the graph state."""
        marker = "loop_worker_ab_cd"
        payload = {
            "session_id": "s",
            "cwd": "/x",
            "tool_name": "spawn_agent",
            "hook_event_name": "PreToolUse",
            "tool_input": {"task_name": marker, "message": f"CODERAILS_GRAPH_TASK={marker}\nwork"},
        }
        base = self.collaborators()
        with patch.object(
            loop_dispatch_guard, "graph_output", side_effect=hook_common.HostResourceError(errno.EMFILE, "x")
        ):
            reason = run_hook(loop_dispatch_guard, payload, **base)
        self.assertIn("not known to be invalid", reason)


if __name__ == "__main__":
    unittest.main()
