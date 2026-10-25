#!/usr/bin/env python3
"""Exercise stop-hook state changes between the initial read and locked consume."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_state_common import atomic_progress_update
from hooks.scripts.loop_stall_guard import main
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.eval_artifact import grading_checksum


class StallGuardRaceTests(HookTestCase):
    """Use real loop files while forcing one write between read and lock."""

    def setUp(self) -> None:
        """Use native Claude transcript and loop paths."""
        super().setUp()
        self.environment["HOME"] = str(self.directory)
        self.environment["CLAUDE_PROJECTS_DIR"] = str(self.directory / ".claude/projects")

    def transcript(self, text: str = "", invocations: int = 1) -> Path:
        """Place the fixture under the session's native transcript name."""
        temporary = super().transcript(text, invocations)
        path = self.directory / ".claude/projects/fixture" / f"{self.session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(path)
        return path

    def stopped(self) -> Path:
        """Add one native graph.py stop tool call to the current turn."""
        path = self.transcript()
        call = {"type": "tool_use", "name": "Bash", "input": {"command": "python3 graph.py stop --category x"}}
        row = {"type": "assistant", "message": {"content": [call]}}
        path.write_text(path.read_text() + json.dumps(row) + "\n")
        return path

    def complete_fixture(self) -> Path:
        """Build a resolved graph with a graded loop suite and retro."""
        graph: dict[str, Any] = {
            "nodes": {},
            "edges": [],
            "joins": {},
            "active_wave": None,
            "hard_stop": None,
            "wave_history": {},
        }
        path = self.progress(graph=graph, proof_disposition="none", work_units={})
        identity = {"session_id": self.session, "loop_id": "loop-test"}
        path.with_name("retro.json").write_text(json.dumps({"schema_version": 2, **identity}))
        suite_path = path.with_name("evals.json")
        suite: dict[str, Any] = {
            "scope": "loop",
            "result": "GO",
            "verification_level": 0,
            "verification_justification": "zero work fixture",
            "revision": 1,
            "evals": [],
            **identity,
        }
        suite_path.write_text(json.dumps(suite))
        suite["grading"] = {"by": "post_evals.py grade-loop", "checksum": grading_checksum(suite_path, "GO")}
        suite_path.write_text(json.dumps(suite))
        return path

    def arm(self, path: Path, *rows: dict[str, Any]) -> None:
        """Set the stop rows on an existing fixture."""
        data = json.loads(path.read_text())
        data["stops"] = list(rows)
        path.write_text(json.dumps(data))

    @staticmethod
    def stop(seq: int, category: str) -> dict[str, Any]:
        """Build a current-revision stop row."""
        return {
            "seq": seq,
            "category": category,
            "reason_code": "other",
            "reason": "r",
            "revision": 1,
            "consumed": False,
            "at": 1.0e9,
        }

    def test_interleaved_revision_change_cannot_consume_old_stop(self) -> None:
        """A writer that advances progress before the locked consume makes Stop block without changing that state."""
        path = self.progress(stops=[self.stop(1, "awaiting-input")])
        payload = self.payload(self.stopped())
        interleaved: list[bytes] = []

        def advance_then_update(target: Path, update: Callable[[dict[str, Any]], dict[str, Any]]) -> bool:
            data = json.loads(target.read_text())
            data["revision"] = 2
            target.write_text(json.dumps(data))
            interleaved.append(target.read_bytes())
            return atomic_progress_update(target, update)

        with (
            patch.dict(os.environ, self.environment),
            patch("hooks.scripts.loop_stall_guard.read_payload", return_value=payload),
            patch("hooks.scripts.loop_stall_guard.atomic_progress_update", side_effect=advance_then_update),
            redirect_stderr(StringIO()),
        ):
            result = main()
        self.assertEqual(result, 2)
        self.assertEqual(path.read_bytes(), interleaved[0])

    def test_foreign_owner_row_cannot_release_stop(self) -> None:
        """A row in a foreign session's state cannot release or change the invoking session's Stop."""
        path = self.progress(session_id="foreign", stops=[self.stop(1, "awaiting-input")])
        before = path.read_bytes()
        result = self.run_hook("loop_stall_guard", self.payload(self.stopped()))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_complete_rechecks_evals_before_locked_consume(self) -> None:
        """A grade withdrawn after the first read makes completion block and leaves the row unconsumed."""
        path = self.complete_fixture()
        self.arm(path, self.stop(1, "complete"))
        payload = self.payload(self.stopped())
        evals = path.with_name("evals.json")

        def withdraw_then_update(target: Path, update: Callable[[dict[str, Any]], dict[str, Any]]) -> bool:
            suite = json.loads(evals.read_text())
            suite["result"] = "NO-GO"
            evals.write_text(json.dumps(suite))
            return atomic_progress_update(target, update)

        with (
            patch.dict(os.environ, self.environment),
            patch("hooks.scripts.loop_stall_guard.read_payload", return_value=payload),
            patch("hooks.scripts.loop_stall_guard.atomic_progress_update", side_effect=withdraw_then_update),
            redirect_stderr(StringIO()),
        ):
            result = main()
        self.assertEqual(result, 2)
        self.assertFalse(json.loads(path.read_text())["stops"][0]["consumed"])
