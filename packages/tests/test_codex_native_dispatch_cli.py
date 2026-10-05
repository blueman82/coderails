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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages/codex/skills/agentic-loop/scripts"))
import graph_contract

ROOT = Path(__file__).resolve().parents[2]
TASK = "loop_worker_6c6f6f70_55335b375d"


def seeded_state() -> dict[str, Any]:
    """A running U3[7] wave with its unused begin-wave dispatch record."""
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
        "state_minor": 2,
        "graph": {
            "nodes": {"U3[7]": node},
            "edges": [],
            "joins": {},
            "hard_stop": None,
            "active_wave": {"wave_id": "wave-2", "revision": 2, "nodes": ["U3[7]"]},
            "dispatches": {},
            "contract_from_revision": 1,
        },
    }
    contract = graph_contract.build_contract(state, "U3[7]", "main")
    identifier, record = graph_contract.make_record(state, "U3[7]", "wave-2", 1, contract, "native")
    record["task_name"] = TASK
    state["graph"]["dispatches"][identifier] = record
    return state


def message_for(state: dict[str, Any]) -> str:
    """The pasted prompt for the seeded record."""
    identifier, record = next(iter(state["graph"]["dispatches"].items()))
    return (
        graph_contract.prompt_prefix(state, identifier, record)
        + "\n"
        + graph_contract.render_sections(record["contract"])
        + "\nImplement."
    )


class NativeDispatchCliTests(unittest.TestCase):
    """Require v3 ownership, a begin-wave record and frozen evals for every spawn in a graph-bound session."""

    def test_v3_native_dispatch_authority(self) -> None:
        """Allow an owned dispatch once; deny replay, missing evals, foreign session, task and bare spawns."""
        plugin = ROOT / "packages/codex"
        with tempfile.TemporaryDirectory() as scratch:
            directory = Path(scratch)
            state_path = directory / "loops/project/parent/progress.json"
            state_path.parent.mkdir(parents=True)
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
            environment = os.environ | {
                "CODERAILS_AGENTIC_LOOP_DIR": str(directory / "loops"),
                "PLUGIN_ROOT": str(plugin),
                "PLUGIN_DATA": str(directory / "data"),
            }
            hook = plugin / "hooks/scripts/loop_dispatch_guard.py"

            def seed() -> dict[str, Any]:
                state = seeded_state()
                state_path.write_text(json.dumps(state), encoding="utf-8")
                evals_path.write_text(json.dumps(evals), encoding="utf-8")
                return state

            def run(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [sys.executable, str(hook)],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    env=environment,
                    check=False,
                )

            def denied(result: subprocess.CompletedProcess[str]) -> bool:
                self.assertEqual(result.returncode, 0, result.stderr)
                return (
                    bool(result.stdout)
                    and json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
                )

            base = seed()
            payload: dict[str, Any] = {
                "tool_name": "spawn_agent",
                "session_id": "parent",
                "cwd": scratch,
                "tool_input": {"task_name": TASK, "message": message_for(base)},
            }
            for role in (None, "worker", "general-purpose"):
                seed()
                if role is not None:
                    payload["tool_input"]["agent_type"] = role
                self.assertFalse(denied(run(payload)), role)
            after = state_path.read_bytes()
            self.assertTrue(denied(run(payload)), "a second spawn with the same envelope is a replay")
            self.assertEqual(state_path.read_bytes(), after)
            for mutation in ("task", "session", "evals", "bare", "foreign role"):
                state = seed()
                altered = json.loads(json.dumps(payload))
                altered["tool_input"].pop("agent_type", None)
                if mutation == "task":
                    altered["tool_input"]["task_name"] = "loop_worker_6c6f6f70_55335b385d"
                elif mutation == "session":
                    altered["session_id"] = "other"
                elif mutation == "bare":
                    altered["tool_input"].update(
                        task_name=TASK, message="CODERAILS_GRAPH_TASK=" + TASK + "\nImplement."
                    )
                elif mutation == "foreign role":
                    altered["tool_input"]["agent_type"] = "source-auditor"
                else:
                    evals_path.unlink()
                self.assertTrue(denied(run(altered)), mutation)
                self.assertEqual(json.loads(state_path.read_text(encoding="utf-8")), state, mutation)


if __name__ == "__main__":
    unittest.main()
