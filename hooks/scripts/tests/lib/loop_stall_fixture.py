"""Shared native Claude Stop fixtures for lifecycle and completion tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib import orders_completion, orders_lifecycle, retro, teardown_steps
from scripts.lib.eval_artifact import grading_checksum


def assemble_test_retro(state_dir: Path, session: str) -> dict[str, Any]:
    """Build a fixture retro with the serialized D4 preparation receipt, without invoking live Muninn."""
    path = state_dir / "progress.json"
    state: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    loop_id = str(state.get("loop_id") or "")
    if state.get("status") != "complete":
        ledger = state_dir / teardown_steps.NAME
        if ledger.is_file():
            rows = [
                row
                for row in teardown_steps.read_rows(state_dir)
                if row["step"] not in {"orders_prepared", "retro_assembled"}
            ]
            ledger.write_text("".join(json.dumps(row) + "\n" for row in rows))
        orders_lifecycle.preparation_path(state_dir, loop_id).unlink(missing_ok=True)
    teardown_steps.record(
        state_dir, "proof_run", session, loop_id, teardown_steps.file_sha(state_dir / "proof_results.jsonl")
    )
    with patch.dict(os.environ, {"PATH": "/nonexistent"}):
        retro.assemble(state_dir, session)
        orders_completion.prepare(path, session, loop_id)
        payload, code = retro.assemble(state_dir, session)
    if code == 2:
        raise AssertionError(payload)
    return cast("dict[str, Any]", json.loads((state_dir / "retro.json").read_text()))


class StallGuardCase(HookTestCase):
    """Provide owned graph, retro, and transcript fixtures."""

    def setUp(self) -> None:
        """Use a native Claude home for graph transcript ownership validation."""
        super().setUp()
        self.environment["HOME"] = str(self.directory)
        self.environment["CLAUDE_PROJECTS_DIR"] = str(self.directory / ".claude/projects")

    def transcript(self, text: str = "", invocations: int = 1) -> Path:
        """Place fixture transcript under its actual native session filename."""
        temporary = super().transcript(text, invocations)
        path = self.directory / ".claude/projects/fixture" / f"{self.session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(path)
        return path

    def complete_fixture(self, stops: list[dict[str, Any]] | None = None) -> Path:
        """Create a zero-work current graph, explicit proof disposition, and graded artifacts."""
        graph: dict[str, Any] = dict(nodes={}, edges=[], joins={}, active_wave=None, hard_stop=None, wave_history={})
        path = self.progress(
            graph=graph,
            proof_disposition="none: no executable surface",
            work_units={},
            stops=stops if stops is not None else [self.stop(1, "complete")],
            created="2026-10-19T00:00:00+00:00",
            updated_at="2026-10-19T00:00:00+00:00",
            authorising_prompt_raw="Complete this bounded fixture loop.",
        )
        config = path.parent.parent / ".coderails/workflow.config.yaml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("memory:\n  backend: off\n")
        identity = {"session_id": self.session, "loop_id": "loop-test"}
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
        suite["grading"] = {
            "by": "post_evals.py grade-loop",
            "checksum": grading_checksum(suite_path, "GO"),
            "amendments_at_grade": 0,
        }
        suite_path.write_text(json.dumps(suite))
        assemble_test_retro(path.parent, self.session)
        return path

    def trace_reasons(self) -> list[str]:
        """Return the non-authoritative trace reason codes written for this session."""
        path = self.directory / "state" / self.session / "trace.jsonl"
        rows = path.read_text().splitlines() if path.is_file() else []
        return [value["reason_code"] for row in rows if (value := json.loads(row)).get("command") == "loop_stall_guard"]

    def arm(self, path: Path, *rows: dict[str, Any]) -> None:
        """Replace the stops array (counters stay), as a fresh `graph.py stop` would."""
        data = json.loads(path.read_text())
        data["stops"] = list(rows)
        path.write_text(json.dumps(data))

    def stopped(self, text: str) -> Path:
        """Transcript whose current turn ran graph.py stop, as a real recorded stop would."""
        path = self.transcript(text)
        call = {"type": "tool_use", "name": "Bash", "input": {"command": "python3 graph.py stop --category x"}}
        row = {"type": "assistant", "message": {"content": [call]}}
        path.write_text(path.read_text() + json.dumps(row) + "\n")
        return path

    @staticmethod
    def stop(seq: int, category: str, revision: int = 1, consumed: bool = False, at: float = 1.0e9) -> dict[str, Any]:
        """Build one recorded stop row exactly as graph.py stop writes it."""
        return {
            "seq": seq,
            "category": category,
            "reason_code": "other",
            "reason": "r",
            "revision": revision,
            "consumed": consumed,
            "at": at,
        }
