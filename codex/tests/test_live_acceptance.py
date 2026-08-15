from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from tests import live_acceptance  # noqa: E402


class LiveAcceptanceNegativeTests(unittest.TestCase):
    def test_live_resume_loads_graph_and_makes_no_second_exec_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            argv = ["live_acceptance.py", "--state", str(state), "--scenario", "live"]
            with patch.object(sys, "argv", argv), patch("runtime.graph.codex_exec", return_value=("done", '{"type":"turn.completed"}')) as invoke:
                self.assertEqual(live_acceptance.main(), 0)
                first = json.loads(state.read_text())
                evidence_count = sum(len(node.get("evidence", [])) for node in first["graph"]["nodes"].values())
                first_calls = invoke.call_count
                self.assertEqual(live_acceptance.main(), 0)
                second = json.loads(state.read_text())
            self.assertEqual(first_calls, 3)
            self.assertEqual(invoke.call_count, first_calls)
            self.assertEqual(sum(len(node.get("evidence", [])) for node in second["graph"]["nodes"].values()), evidence_count)
            self.assertEqual(first["revision"], second["revision"])

    def run_scenario(self, scenario: str) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            argv = ["live_acceptance.py", "--state", str(state), "--scenario", scenario]
            with patch.object(sys, "argv", argv), patch("runtime.graph.codex_exec", return_value=("done", '{"type":"turn.completed"}')):
                result = live_acceptance.main()
            self.assertEqual(result, 1)
            return json.loads(state.read_text())

    def test_failure_scenario_reaches_hard_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            argv = ["live_acceptance.py", "--state", str(state), "--scenario", "failure"]
            with patch.object(sys, "argv", argv), patch("runtime.graph.codex_exec", return_value=("failed", "provider failure")):
                result = live_acceptance.main()
            self.assertEqual(result, 1)
            saved = json.loads(state.read_text())
            self.assertEqual(saved["graph"]["nodes"]["A"]["outcome"], "hard-stop")

    def test_missing_scenario_blocks_join(self) -> None:
        saved = self.run_scenario("missing")
        self.assertEqual(saved["graph"]["nodes"]["B"]["outcome"], "hard-stop")
        self.assertEqual(saved["graph"]["nodes"]["C"]["outcome"], "hard-stop")


if __name__ == "__main__":
    unittest.main()
