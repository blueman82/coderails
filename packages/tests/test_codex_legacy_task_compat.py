"""Keep stored pre-loop task evidence verifiable without authorizing legacy dispatch."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
import graph
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError


class LegacyTaskCompatibilityTests(unittest.TestCase):
    """Preserve owned historical evidence while rejecting old names for new dispatches."""

    def setUp(self) -> None:
        """Place native transcript fixtures under an isolated home directory."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.home).start()

    def _state(self, active: bool = False) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "session_id": "parent",
            "loop_id": "loop",
            "revision": 2,
            "status": "in-progress",
            "graph": {
                "nodes": {
                    "U3[1]": {
                        "retry": {"attempts": 0},
                        "respawn": {"generation": 0},
                        "status": "done" if not active else "running",
                        "evidence": (
                            [
                                {
                                    "kind": "codex_agent",
                                    "attempt": 1,
                                    "wave_id": "wave-1",
                                    "spawn_call_id": "call",
                                    "agent_thread_id": "child",
                                    "task_complete_turn_id": "turn",
                                }
                            ]
                            if not active
                            else []
                        ),
                    }
                },
                "joins": {},
                "active_wave": {"wave_id": "wave-1", "revision": 2, "nodes": ["U3[1]"]} if active else None,
            },
        }

    def _write_legacy_transcripts(self) -> None:
        task = "loop_worker_55335b315d"
        sessions = self.home / ".codex/sessions"
        sessions.mkdir(parents=True)
        parent_records = [
            {"type": "session_meta", "payload": {"id": "parent"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "spawn_agent",
                    "namespace": "collaboration",
                    "call_id": "call",
                    "arguments": json.dumps({"task_name": task}),
                },
            },
            {
                "type": "event_msg",
                "payload": {
                    "item": {
                        "type": "SubAgentActivity",
                        "kind": "started",
                        "id": "call",
                        "agent_thread_id": "child",
                        "agent_path": f"/root/{task}",
                    }
                },
            },
        ]
        child_records = [
            {
                "timestamp": "2026-09-21T00:00:01Z",
                "type": "session_meta",
                "payload": {
                    "id": "child",
                    "parent_thread_id": "parent",
                    "session_id": "parent",
                    "thread_source": "subagent",
                    "agent_role": None,
                    "source": {
                        "subagent": {
                            "thread_spawn": {
                                "parent_thread_id": "parent",
                                "depth": 1,
                                "agent_role": None,
                                "agent_path": f"/root/{task}",
                            }
                        }
                    },
                },
            },
            {
                "timestamp": "2026-09-21T00:00:02Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn"},
            },
            {
                "timestamp": "2026-09-21T00:00:03Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": "turn"},
            },
        ]
        for name, records in (("fixture-parent.jsonl", parent_records), ("fixture-child.jsonl", child_records)):
            (sessions / name).write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")

    def test_owned_stored_legacy_identity_remains_verifiable(self) -> None:
        """Validate old task spelling only through an existing owned evidence reference."""
        self._write_legacy_transcripts()
        validate_worker_evidence(self._state())

    def test_legacy_identity_cannot_authorize_fresh_dispatch(self) -> None:
        """A node-only historical task name cannot authorize a new loop dispatch."""
        state_path = self.home / "progress.json"
        state_path.write_text(json.dumps(self._state(active=True)), encoding="utf-8")
        with self.assertRaises(GraphError):
            graph.authorize_dispatch(state_path, "parent", "loop_worker_55335b315d", self.home / "evals.json")


if __name__ == "__main__":
    unittest.main()
