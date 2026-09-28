"""Exercise native v3 dispatch through the real hook and graph CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


class NativeDispatchCliTests(unittest.TestCase):
    """Require v3 ownership and frozen evals for native worker labels."""

    def test_v3_native_dispatch_authority(self) -> None:
        """Allow owned workers; deny missing evals and foreign session/task."""
        root = Path(__file__).resolve().parents[2]
        plugin = root / "packages/codex"
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            state_path = directory / "loops/project/parent/progress.json"
            state_path.parent.mkdir(parents=True)
            node: dict[str, Any] = {
                "label": "Build unit 7",
                "status": "running",
                "outcome": "running",
                "retry": {"attempts": 0, "max": 2},
                "respawn": {"generation": 0, "intent": None},
                "evidence": [],
            }
            state: dict[str, Any] = {
                "schema_version": 3,
                "session_id": "parent",
                "loop_id": "loop",
                "revision": 2,
                "status": "in-progress",
                "graph": {
                    "nodes": {"U3[7]": node},
                    "edges": [],
                    "joins": {},
                    "hard_stop": None,
                    "active_wave": {"wave_id": "wave-2", "revision": 2, "nodes": ["U3[7]"]},
                },
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")
            evals = {
                "session_id": "parent",
                "loop_id": "loop",
                "scope": "loop",
                "task_ref": "loop",
                "verification_justification": "Native dispatch fixture",
                "verification_level": 1,
                "frozen_sha": "fixture-sha",
                "result": None,
                "grading": None,
                "evals": [{"id": "E1", "priority": "P0", "mode": "agent-run"}],
            }
            evals_path = state_path.with_name("evals.json")
            evals_path.write_text(json.dumps(evals), encoding="utf-8")
            task = "loop_worker_55335b375d"
            payload: dict[str, Any] = {
                "tool_name": "spawn_agent",
                "session_id": "parent",
                "cwd": scratch,
                "tool_input": {"task_name": task, "message": f"CODERAILS_GRAPH_TASK={task}\nImplement."},
            }
            environment = os.environ | {
                "CODERAILS_AGENTIC_LOOP_DIR": str(directory / "loops"),
                "PLUGIN_ROOT": str(plugin),
                "PLUGIN_DATA": str(directory / "data"),
            }
            hook = plugin / "hooks/scripts/loop_dispatch_guard.py"
            for role in (None, "worker", "general-purpose"):
                if role is not None:
                    payload["tool_input"]["agent_type"] = role
                result = subprocess.run(
                    [sys.executable, str(hook)],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "", result.stdout)
            for mutation in ("task", "session", "evals"):
                altered = json.loads(json.dumps(payload))
                if mutation == "task":
                    altered["tool_input"].update(
                        task_name="loop_worker_55335b385d", message="CODERAILS_GRAPH_TASK=loop_worker_55335b385d"
                    )
                elif mutation == "session":
                    altered["session_id"] = "other"
                else:
                    evals_path.unlink()
                result = subprocess.run(
                    [sys.executable, str(hook)],
                    input=json.dumps(altered),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )
                self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state)


if __name__ == "__main__":
    unittest.main()
