"""Native Codex evidence for a scout stage that has no work to dispatch."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
from graph_evidence import bind_worker_evidence, validate_worker_evidence
from graph_identity import GraphError, task_name
from graph_scout_skip import bind as bind_skip
from graph_scout_skip import verify as verify_skip

from packages.tests import test_codex_native_evidence as native_fixture


class ScoutSkipTests(unittest.TestCase):
    """Check Codex skip binding and completion revalidation."""

    def setUp(self) -> None:
        """Reuse the native parent-transcript fixture."""
        self.fixture = native_fixture.NativeEvidenceTests("test_roleless_native_binding_and_revalidation")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.state["graph"]["nodes"] = {
            "S2.5": {"retry": {"attempts": 0}, "respawn": {"generation": 0}, "status": "running", "evidence": []}
        }
        self.fixture.wave["nodes"] = ["S2.5"]
        self.fixture.state["graph"]["wave_history"] = {"wave-1": {"cursor": 1, "nodes": ["S2.5"], "revision": 2}}

    def test_no_fork_has_typed_skip_evidence(self) -> None:
        """A first-wave no-fork decision skips without inventing a child thread."""
        case = self.fixture
        case.state["graph"]["dispatches"] = {
            "issued": {"node_id": "S2.5", "wave_id": "wave-1", "attempt": 1, "revision": 2, "authorized": None}
        }
        case.write_transcripts()
        reason = "no_design_fork: plan has no unresolved design choice"
        ref = bind_worker_evidence(case.state, case.wave, skip_evidence={"S2.5": reason})[0]["S2.5"]
        self.assertEqual(ref["kind"], "graph_skip")
        case.state["graph"]["nodes"]["S2.5"].update(status="skipped", evidence=[reason, ref])
        case.state["graph"]["active_wave"] = None
        validate_worker_evidence(case.state)
        case.state["graph"]["nodes"]["S2.5"]["evidence"][0] = "no_design_fork: altered"
        with self.assertRaisesRegex(GraphError, "reason changed"):
            validate_worker_evidence(case.state)
        case.state["graph"]["nodes"]["S2.5"]["evidence"][0] = reason
        ref["cursor"] = 999
        with self.assertRaisesRegex(GraphError, "wave cursor"):
            validate_worker_evidence(case.state)
        ref["cursor"] = 1
        ref["attempt"] = True
        with self.assertRaisesRegex(GraphError, "invalid scout skip fields"):
            validate_worker_evidence(case.state)

    def test_unverified_non_independent_skip_refuses(self) -> None:
        """A caller's approval claim does not pass the native binder."""
        case = self.fixture
        case.write_transcripts()
        with self.assertRaisesRegex(GraphError, "approval"):
            bind_worker_evidence(case.state, case.wave, skip_evidence={"S2.5": "non_independent: human approved"})

    def test_scout_skip_cannot_replace_native_spawn(self) -> None:
        """A real native spawn excludes a no-work skip."""
        case = self.fixture
        task = task_name("loop", "S2.5", 1)
        case.arguments["task_name"] = task
        case.activity["agent_path"] = f"/root/{task}"
        case.write_transcripts()
        with self.assertRaisesRegex(GraphError, "cannot reuse a native spawn"):
            bind_worker_evidence(case.state, case.wave, skip_evidence={"S2.5": "no_design_fork: false claim"})

    def test_approved_fallback_binds_direct_user_reply(self) -> None:
        """A failed scout needs a matching request and direct user approval."""
        case = self.fixture
        first_task = task_name("loop", "S2.5", 1)
        request = (
            "Coderails: Approve a non-independent design-scout fallback for loop loop, "
            "node S2.5, attempt 2? Reply approve or deny."
        )
        rows: list[dict[str, Any]] = [
            {"type": "session_meta", "payload": {"id": "parent"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "spawn_agent",
                    "namespace": "collaboration",
                    "call_id": "old",
                    "arguments": json.dumps({"task_name": first_task}),
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "old", "output": "agent thread limit reached"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": request}],
                },
            },
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "approve"}]},
            },
        ]
        parent = case.directory / "fixture-parent.jsonl"

        def save() -> None:
            parent.write_text("".join(json.dumps(row) + "\n" for row in rows))

        save()
        node = case.state["graph"]["nodes"]["S2.5"]
        node["retry"]["attempts"] = 1
        node["evidence"] = [
            {
                "kind": "codex_agent",
                "attempt": 1,
                "wave_id": "wave-1",
                "spawn_call_id": "old",
                "outcome": "launch_refused",
            }
        ]
        case.wave.update(wave_id="wave-3", transcript_cursor=5)
        case.state["graph"]["wave_history"] = {"wave-3": {"cursor": 5, "nodes": ["S2.5"], "revision": 4}}
        case.state["graph"]["dispatches"] = {
            "issued": {"node_id": "S2.5", "wave_id": "wave-3", "attempt": 2, "revision": 4, "authorized": None}
        }
        refusals = {"old": (2, first_task)}
        evidence = "non_independent: human approved design fallback"
        ref = bind_skip(case.state, case.wave, "S2.5", evidence, 5, {}, refusals)
        self.assertEqual(ref["reason"], "non_independent")
        node.update(status="skipped", evidence=[*node["evidence"], evidence, ref])
        case.state["revision"] = 4
        case.state["graph"]["active_wave"] = None
        verify_skip(case.state, "S2.5", ref, {}, refusals)
        validate_worker_evidence(case.state)
        ref["approval_line"] = 4
        with self.assertRaisesRegex(GraphError, "approval"):
            verify_skip(case.state, "S2.5", ref, {}, refusals)
        ref["approval_line"] = 5
        rows[4]["payload"]["content"][0]["text"] = "deny"
        save()
        with self.assertRaisesRegex(GraphError, "approval"):
            verify_skip(case.state, "S2.5", ref, {}, refusals)
        rows[4]["payload"]["content"][0]["text"] = "approve"
        rows[3]["payload"]["content"][0]["text"] = request.replace("loop loop", "loop foreign")
        save()
        with self.assertRaisesRegex(GraphError, "approval"):
            verify_skip(case.state, "S2.5", ref, {}, refusals)
        rows[3]["payload"]["content"][0]["text"] = request
        rows.insert(
            4,
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "New"}, {"type": "output_text", "text": "question"}],
                },
            },
        )
        save()
        with self.assertRaisesRegex(GraphError, "approval"):
            verify_skip(case.state, "S2.5", ref, {}, refusals)


if __name__ == "__main__":
    unittest.main()
