"""Native graph commands record and flush typed decisions on both providers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from hooks.scripts.tests.lib import claude_transcript_fixture as fixture  # noqa: E402
from scripts.lib import decision_record as dr  # noqa: E402
from scripts.tests.fake_muninn_case import LATER, PROMPT, SESSION, StoreCase  # noqa: E402

GRAPH_SCRIPTS = (
    ROOT / "skills/agentic-loop/scripts/graph.py",
    ROOT / "packages/codex/skills/agentic-loop/scripts/graph.py",
)


class DecisionCliTests(StoreCase):
    """Run each provider CLI with a real schema-3 state and hermetic fake Muninn."""

    with_store = True

    def test_record_decision_guidance_names_required_caller_binding(self) -> None:
        """The executable examples and both provider guides name the CLI's required identity fields."""
        examples = (
            ROOT / "skills/agentic-loop/phases-setup.md",
            ROOT / "docs/REFERENCE.md",
        )
        for path in examples:
            with self.subTest(example=path.name):
                line = next(
                    line for line in path.read_text().splitlines() if "graph.py record-decision <progress.json>" in line
                )
                self.assertIn("--loop-id", line)
                self.assertIn("--revision", line)
        for path in (
            ROOT / "skills/agentic-loop/SKILL.md",
            ROOT / "packages/codex/skills/agentic-loop/SKILL.md",
        ):
            with self.subTest(guide=path):
                guide = path.read_text()
                self.assertIn("--loop-id", guide)
                self.assertIn("--revision", guide)

    def setUp(self) -> None:
        """Create an owned graph whose authorising prompt is in the fake transcript."""
        super().setUp()
        self.path = self.tmp / "progress.json"
        self.put({**fixture.state(), "session_id": SESSION, "loop_id": "L1", "authorising_prompt_raw": PROMPT})

    def put(self, state: dict[str, Any]) -> None:
        """Write a test graph fixture."""
        self.path.write_text(json.dumps(state))

    def state(self) -> dict[str, Any]:
        """Read the resulting graph."""
        return json.loads(self.path.read_text())  # type: ignore[no-any-return]

    def run_graph(self, script: Path, *args: str) -> tuple[int, dict[str, Any]]:
        """Invoke a native graph command and parse its JSON result."""
        result = subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            text=True,
            env={**os.environ, "CLAUDE_CODE_SESSION_ID": SESSION},
            check=False,
        )
        return result.returncode, json.loads(result.stdout) if result.stdout.strip().startswith("{") else {}

    def test_rearmed_same_session_refuses_stale_caller(self) -> None:
        """Both CLIs compare the caller's loop and revision while holding the graph lock."""
        for script in GRAPH_SCRIPTS:
            with self.subTest(provider=script):
                fresh = {**fixture.state(), "session_id": SESSION, "loop_id": "L2", "revision": 7}
                self.put(fresh)
                before = self.path.read_bytes()
                code, out = self.run_graph(
                    script,
                    "record-decision",
                    str(self.path),
                    "--session",
                    SESSION,
                    "--loop-id",
                    "L1",
                    "--revision",
                    "7",
                    "--phase",
                    "2.5",
                    "--decision",
                    "stale choice",
                )
                self.assertEqual((code, out.get("reason_code")), (2, "decision_wrong_loop"))
                self.assertEqual(self.path.read_bytes(), before)
                code, out = self.run_graph(
                    script,
                    "record-decision",
                    str(self.path),
                    "--session",
                    SESSION,
                    "--loop-id",
                    "L2",
                    "--revision",
                    "6",
                    "--phase",
                    "2.5",
                    "--decision",
                    "stale choice",
                )
                self.assertEqual((code, out.get("reason_code")), (2, "decision_wrong_revision"))
                self.assertEqual(self.path.read_bytes(), before)

    def test_record_and_flush_are_native_and_chain_checked(self) -> None:
        """Both graph CLIs persist a hash; a tampered chain refuses further record and flush."""
        for script in GRAPH_SCRIPTS:
            with self.subTest(provider=script):
                self.put({**fixture.state(), "session_id": SESSION, "loop_id": "L1", "authorising_prompt_raw": PROMPT})
                code, out = self.run_graph(
                    script,
                    "record-decision",
                    str(self.path),
                    "--session",
                    SESSION,
                    "--loop-id",
                    "L1",
                    "--revision",
                    str(self.state()["revision"]),
                    "--phase",
                    "2.5",
                    "--decision",
                    "adopt shape A",
                )
                self.assertEqual((code, out.get("recorded"), out.get("seq")), (0, True, 1))
                rows = self.state()["decisions_absorbed"]
                self.assertEqual((len(rows), dr.verify_chain(rows)), (1, []))
                rows[0]["decision"] = "tampered"
                rows[0]["muninn"] = {"state": "pending"}
                self.put({**self.state(), "decisions_absorbed": rows})
                before = self.state()
                code, out = self.run_graph(
                    script,
                    "record-decision",
                    str(self.path),
                    "--session",
                    SESSION,
                    "--loop-id",
                    "L1",
                    "--revision",
                    str(self.state()["revision"]),
                    "--phase",
                    "2.6",
                    "--decision",
                    "later",
                )
                self.assertEqual((code, out.get("reason_code")), (2, "decision_invalid_chain"))
                code, out = self.run_graph(script, "flush-decisions", str(self.path), "--session", SESSION)
                self.assertEqual((code, out.get("reason_code")), (2, "decision_invalid_chain"))
                self.assertEqual(self.state(), before)

    def test_degraded_record_can_flush_with_valid_user_quote(self) -> None:
        """A short approval degrades, then the native flush command syncs the same row."""
        for script in GRAPH_SCRIPTS:
            with self.subTest(provider=script):
                self.put({**fixture.state(), "session_id": SESSION, "loop_id": "L1", "authorising_prompt_raw": "yes"})
                code, out = self.run_graph(
                    script,
                    "record-decision",
                    str(self.path),
                    "--session",
                    SESSION,
                    "--loop-id",
                    "L1",
                    "--revision",
                    str(self.state()["revision"]),
                    "--phase",
                    "2.5",
                    "--decision",
                    "adopt shape A",
                )
                self.assertEqual((code, out.get("muninn", {}).get("state")), (3, "degraded"))
                code, out = self.run_graph(
                    script,
                    "flush-decisions",
                    str(self.path),
                    "--session",
                    SESSION,
                    "--cite-quote",
                    LATER,
                )
                self.assertEqual((code, [x["seq"] for x in out.get("synced", [])]), (0, [1]))
                self.assertEqual(self.state()["decisions_absorbed"][0]["muninn"]["state"], "written")


if __name__ == "__main__":
    import unittest

    unittest.main()
