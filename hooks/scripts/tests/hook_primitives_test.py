#!/usr/bin/env python3
"""Exercise bounded stdin, tolerant transcript parsing, and atomic loop ownership."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.discipline_common import extract_last_text, file_count
from hooks.scripts.lib.loop_state_common import LoopState, atomic_progress_update


class HookPrimitivesTests(unittest.TestCase):
    """Preserve pipe-deadline and non-destructive state update behavior."""

    def test_open_pipe_deadline(self) -> None:
        """A producer that leaves its pipe open cannot extend the input deadline."""
        command = [sys.executable, "-c", "import hook_common;print(hook_common.read_payload(0.15))"]
        with subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, cwd=Path(__file__).resolve().parents[1]
        ) as process:
            assert process.stdin is not None
            process.stdin.write(b'{"session_id":"s"}')
            process.stdin.flush()
            started = time.monotonic()
            process.wait(timeout=1)
            self.assertLess(time.monotonic() - started, 0.8)
            assert process.stdout is not None
            self.assertIn(b"session_id", process.stdout.read())

    def test_completed_legacy_state_is_not_an_off_switch(self) -> None:
        """Legacy and foreign state cannot claim this native session completed its loop."""
        for version in (None, 1, 2):
            state = LoopState(
                Path("unused"),
                "S1",
                1,
                {"schema_version": version, "session_id": "S1", "status": "complete", "completed_marker": 1},
            )
            self.assertFalse(state.complete)

    def test_state_lock_and_failed_transform(self) -> None:
        """Contention and invalid updates leave bytes unchanged and release owned locks."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "progress.json"
            path.write_text('{"revision":1}')
            lock = Path(f"{path}.lock")
            lock.mkdir()
            with patch.dict(os.environ, {"CLAUDE_HOOK_MAX_ATTEMPTS": "1"}):
                self.assertFalse(atomic_progress_update(path, lambda state: {**state, "revision": 2}))
            self.assertEqual(path.read_text(), '{"revision":1}')
            lock.rmdir()
            self.assertFalse(atomic_progress_update(path, lambda state: {"bad": {1}}))
            self.assertEqual(path.read_text(), '{"revision":1}')
            self.assertFalse(lock.exists())
            self.assertTrue(atomic_progress_update(path, lambda state: {**state, "revision": 2}))
            self.assertEqual(json.loads(path.read_text()), {"revision": 2})

    def test_completion_cli_uses_native_invocation_ordinal_and_atomic_writer(self) -> None:
        """Direct teardown CLI preserves state and stamps actual transcript invocation count."""
        helper = Path(__file__).resolve().parents[1] / "lib/loop_state_common.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "state/-work-project/S1/progress.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version":3,"session_id":"S1","status":"in-progress","custom":{"key":"value"}}')
            trace = root / "projects/fixture/S1.jsonl"
            trace.parent.mkdir(parents=True)
            line = {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Skill", "input": {"skill": "coderails:agentic-loop"}}]
                },
            }
            trace.write_text((json.dumps(line) + "\n") * 2)
            environment = {
                **os.environ,
                "CLAUDE_AGENTIC_LOOP_DIR": str(root / "state"),
                "CLAUDE_PROJECTS_DIR": str(root / "projects"),
                "CLAUDE_HOOK_MAX_ATTEMPTS": "1",
            }
            result = subprocess.run(
                [sys.executable, str(helper), "mark-complete", "/work/project", "S1"],
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(path.read_text()),
                {
                    "schema_version": 3,
                    "session_id": "S1",
                    "status": "complete",
                    "completed_marker": 2,
                    "custom": {"key": "value"},
                },
            )
            self.assertFalse(Path(str(path) + ".lock").exists())

    def test_tolerant_current_turn(self) -> None:
        """Malformed records and tool results do not erase current-turn edits or text."""
        lines = [
            {"type": "user", "message": {"content": "start"}},
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "x"}}]},
            },
            {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "final"}]}},
            {"message": "bad"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_text("\n".join(json.dumps(line) for line in lines) + "\n{broken")
            self.assertEqual(file_count(str(path)), 1)
            self.assertEqual(extract_last_text(str(path), 200), "final")


if __name__ == "__main__":
    unittest.main()
