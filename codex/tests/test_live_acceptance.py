from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT / "codex"))
from tests import live_acceptance  # noqa: E402
from runtime.gate_producer import produce  # noqa: E402


class LiveAcceptanceNegativeTests(unittest.TestCase):
    def fake_codex(self, directory: str) -> None:
        binary = Path(directory) / "codex"
        binary.write_text("#!/bin/sh\nprompt=$(cat)\nmarker=$(printf '%s' \"$prompt\" | grep -oE 'PHASE_[A-Za-z0-9_./-]+_OK|GATE_[A-Za-z0-9_./-]+_OK' | head -1)\nprintf '%s\\n' \"{\\\"type\\\":\\\"item.completed\\\",\\\"marker\\\":\\\"$marker\\\"}\"\nprintf '%s\\n' '{\"type\":\"turn.completed\"}'\n")
        binary.chmod(0o755)

    def test_gate_producer_rejects_unrelated_success_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "review.json"
            raw = Path(directory) / "review.raw.jsonl"
            with self.assertRaisesRegex(RuntimeError, "GATE_REVIEW_OK"):
                produce("review", artifact, raw, "run", "1", "head", directory, executor=lambda _prompt, _cwd: ("done", '{"type":"turn.completed"}\nUNRELATED_OK\n'))
            self.assertFalse(artifact.exists())
            self.assertIn("turn.completed", raw.read_text())

    def test_canonical_acceptance_creates_all_run_bound_artifacts_and_lifecycle_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            self.fake_codex(directory)
            with patch.dict(os.environ, {"PATH": f"{directory}:{os.environ['PATH']}"}):
                self.assertEqual(live_acceptance.run_canonical(state), 0)
            saved = json.loads(state.read_text())
            self.assertEqual(saved["status"], "complete")
            for gate in ("review", "eval", "proof", "integrity", "wiki", "teardown"):
                artifact = Path(directory) / "artifacts" / f"{gate}.json"
                value = json.loads(artifact.read_text())
                self.assertEqual({value[k] for k in ("schema_version", "gate", "provider", "run_id", "revision", "head")} , {1, gate, "codex", saved["run"]["run_id"], saved["run"]["revision"], saved["run"]["head"]})
                self.assertTrue(Path(directory, "artifacts", f"{gate}.raw.jsonl").is_file())

    def test_canonical_lifecycle_refuses_missing_and_stale_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            self.fake_codex(directory)
            with patch.dict(os.environ, {"PATH": f"{directory}:{os.environ['PATH']}"}):
                self.assertEqual(live_acceptance.run_canonical(state), 0)
            saved = json.loads(state.read_text())
            missing = json.loads(json.dumps(saved))
            missing["gates"].pop("wiki")
            self.assertFalse(live_acceptance.validate({"event": "complete", "state": missing})[0])
            stale = json.loads(json.dumps(saved))
            stale["run"]["head"] = "stale-head"
            self.assertFalse(live_acceptance.validate({"event": "complete", "state": stale})[0])
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
