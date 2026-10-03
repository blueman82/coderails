"""Native dispatch provenance contracts for typed and role-less runtimes."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/hooks/scripts"))
from graph_evidence import bind_worker_evidence, validate_worker_evidence
from graph_identity import GraphError, legacy_task_name, task_name


class NativeEvidenceTests(unittest.TestCase):
    """Exercise transcript binding without mutating graph state."""

    def setUp(self) -> None:
        """Create independent parent and child transcript fixtures."""
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.home = Path(self.scratch.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.home).start()
        self.directory = self.home / ".codex/sessions"
        self.directory.mkdir(parents=True)
        self.task = task_name("loop", "U3[1]", 1)
        self.arguments: dict[str, Any] = {"task_name": self.task}
        self.call: dict[str, Any] = {
            "type": "function_call",
            "name": "spawn_agent",
            "namespace": "collaboration",
            "call_id": "call",
            "arguments": "",
        }
        self.activity: dict[str, Any] = {
            "type": "SubAgentActivity",
            "kind": "started",
            "id": "call",
            "agent_thread_id": "child",
            "agent_path": f"/root/{self.task}",
        }
        self.spawn: dict[str, Any] = {
            "parent_thread_id": "parent",
            "depth": 1,
            "agent_role": None,
            "agent_path": f"/root/{self.task}",
        }
        self.metadata: dict[str, Any] = {
            "id": "child",
            "parent_thread_id": "parent",
            "session_id": "parent",
            "thread_source": "subagent",
            "agent_role": None,
            "source": {"subagent": {"thread_spawn": self.spawn}},
        }
        self.wave: dict[str, Any] = {"wave_id": "wave-1", "nodes": ["U3[1]"], "transcript_cursor": 1}
        self.state: dict[str, Any] = {
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
                        "status": "pending",
                        "evidence": [],
                    }
                },
                "joins": {},
                "active_wave": self.wave,
            },
        }
        self.extra_parent: list[dict[str, Any]] = []
        self.extra_child: list[dict[str, Any]] = []
        self.terminal = "task_complete"

    def _write_transcripts(self) -> None:
        self.call["arguments"] = json.dumps(self.arguments)
        parent = [
            {"type": "session_meta", "payload": {"id": "parent"}},
            {"type": "response_item", "payload": self.call},
            {"type": "event_msg", "payload": {"item": self.activity}},
            *self.extra_parent,
        ]
        child = [
            {"timestamp": "2026-09-21T00:00:01Z", "type": "session_meta", "payload": self.metadata},
            {
                "timestamp": "2026-09-21T00:00:02Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "turn"},
            },
            {
                "timestamp": "2026-09-21T00:00:03Z",
                "type": "event_msg",
                "payload": {"type": self.terminal, "turn_id": "turn"},
            },
            *self.extra_child,
        ]
        for identity, records in (("parent", parent), ("child", child)):
            (self.directory / f"fixture-{identity}.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
            )

    def _bind(self) -> dict[str, Any]:
        self._write_transcripts()
        return bind_worker_evidence(self.state, self.wave)[0]["U3[1]"]

    def _reject(self) -> None:
        before = copy.deepcopy(self.state)
        with self.assertRaises(GraphError):
            self._bind()
        self.assertEqual(self.state, before)

    def _sibling(self, status: str, attempts: int = 0) -> None:
        """Add an unrelated second node with the given status and no worker evidence."""
        self.state["graph"]["nodes"]["U3[2]"] = {
            "retry": {"attempts": attempts},
            "respawn": {"generation": 0},
            "status": status,
            "evidence": [],
        }

    def test_non_terminal_siblings_need_no_completion_evidence(self) -> None:
        """Binding a wave must not demand transcript evidence from pending, ready or running siblings."""
        for status in ("pending", "ready", "running"):
            with self.subTest(status=status):
                self._sibling(status)
                self.assertEqual(self._bind()["agent_thread_id"], "child")

    def test_terminal_and_failed_states_still_require_transcript_evidence(self) -> None:
        """Done, skipped and retried nodes without references stay rejected, and so does a complete check."""
        for status, attempts in (("done", 0), ("skipped", 0), ("pending", 1), ("stale", 0)):
            with self.subTest(status=status, attempts=attempts):
                self._sibling(status, attempts)
                self._reject()
        self._sibling("pending")
        self.state["graph"]["active_wave"] = None
        self.state["graph"]["nodes"]["U3[1]"].update(status="done", evidence=[self._bind()])
        with self.assertRaises(GraphError):
            validate_worker_evidence(self.state)

    def test_roleless_native_binding_and_revalidation(self) -> None:
        """Bind current native evidence and recheck its stored provenance."""
        reference = self._bind()
        self.assertEqual(reference["agent_thread_id"], "child")
        self.state["graph"]["nodes"]["U3[1]"].update(status="done", evidence=[reference])
        self.state["graph"]["active_wave"] = None
        validate_worker_evidence(self.state)
        self.metadata["agent_role"] = "explorer"
        self._write_transcripts()
        with self.assertRaises(GraphError):
            validate_worker_evidence(self.state)

    def test_current_wave_rejects_legacy_task_identity(self) -> None:
        """Historical names remain ineligible for newly bound native spawns."""
        self.task = legacy_task_name("U3[1]")
        self.arguments["task_name"] = self.task
        self.activity["agent_path"] = f"/root/{self.task}"
        self.spawn["agent_path"] = f"/root/{self.task}"
        self._reject()

    def test_typed_native_binding(self) -> None:
        """Preserve the typed native dispatch contract."""
        self.arguments["agent_type"] = "worker"
        self.call.pop("namespace")
        self.metadata["agent_role"] = self.spawn["agent_role"] = "worker"
        self._bind()

    def test_conflicting_native_roles_rejected(self) -> None:
        """Bind the actual requested role, never a hardcoded custom role."""
        self.arguments["agent_type"] = "worker"
        self.metadata["agent_role"] = "worker"
        self.spawn["agent_role"] = "explorer"
        self._reject()

    def test_native_collab_event_role_binding(self) -> None:
        """Older native events bind their actual role and nickname to the child."""
        self.call["name"] = "other"
        self.activity["kind"] = "other"
        self.metadata["agent_role"] = self.spawn["agent_role"] = "worker"
        self.metadata["agent_nickname"] = self.spawn["agent_nickname"] = "Ada"
        self.spawn["agent_path"] = None
        self.extra_parent = [
            {
                "type": "event_msg",
                "payload": {
                    "item": {
                        "type": "CollabAgentToolCall",
                        "tool": "spawn_agent",
                        "status": "completed",
                        "id": "native-call",
                        "prompt": f"CODERAILS_GRAPH_TASK={self.task}\nImplement.",
                        "receiver_thread_ids": ["child"],
                        "receiver_agents": [{"thread_id": "child", "agent_role": "worker", "agent_nickname": "Ada"}],
                    }
                },
            }
        ]
        self._bind()
        self.spawn["agent_role"] = "explorer"
        self._reject()

    def test_invalid_provenance_rejected(self) -> None:
        """Reject mismatched dispatch identities and stale cursors."""
        cases = [
            (self.call, "namespace", "functions"),
            (self.arguments, "agent_type", "explorer"),
            (self.arguments, "agent_type", None),
            (self.arguments, "task_name", "unregistered"),
            (self.arguments, "task_name", task_name("loop", "U3[2]", 1)),
            (self.activity, "agent_path", f"/other/{self.task}"),
            (self.activity, "agent_thread_id", "other-child"),
            (self.metadata, "parent_thread_id", "other"),
            (self.metadata, "session_id", "other"),
            (self.metadata, "agent_role", "loop-worker"),
            (self.spawn, "agent_role", "loop-worker"),
            (self.spawn, "depth", 2),
            (self.spawn, "parent_thread_id", "other"),
            (self.spawn, "agent_path", f"/root/{self.task}_a2"),
            (self.wave, "transcript_cursor", 2),
        ]
        for target, key, value in cases:
            with self.subTest(key=key, value=value):
                present, original = key in target, target.get(key)
                target[key] = value
                self._reject()
                if present:
                    target[key] = original
                else:
                    target.pop(key)

    def test_missing_native_shape_fields_rejected(self) -> None:
        """Require the observed namespace and explicit nested native role field."""
        for target, key in ((self.call, "namespace"), (self.spawn, "agent_role")):
            with self.subTest(key=key):
                original = target.pop(key)
                self._reject()
                target[key] = original

    def test_live_roleless_metadata_without_top_role(self) -> None:
        """Bind the observed native metadata shape without inventing a role field."""
        self.metadata.pop("agent_role")
        self.metadata.update(
            {
                "forked_from_id": None,
                "timestamp": "2026-09-21T00:00:01Z",
                "cwd": "/fixture",
                "runtime_workspace_roots": [],
                "originator": "fixture",
                "cli_version": "fixture",
                "agent_nickname": None,
                "agent_path": f"/root/{self.task}",
                "model_provider": "fixture",
                "base_instructions": {},
                "history_mode": "fixture",
                "subagent_history_start_ordinal": 0,
                "multi_agent_version": "fixture",
                "context_window": 0,
                "git": {},
            }
        )
        reference = self._bind()
        self.state["graph"]["nodes"]["U3[1]"].update(status="done", evidence=[reference])
        self.state["graph"]["active_wave"] = None
        validate_worker_evidence(self.state)
        self.metadata["agent_path"] = "/root/other"
        self._write_transcripts()
        with self.assertRaises(GraphError):
            validate_worker_evidence(self.state)
        self.metadata["agent_path"] = f"/root/{self.task}"
        self.metadata["agent_role"] = "worker"
        self._write_transcripts()
        with self.assertRaises(GraphError):
            validate_worker_evidence(self.state)
        self.metadata.pop("agent_role")
        self.spawn.pop("agent_role")
        self._write_transcripts()
        with self.assertRaises(GraphError):
            validate_worker_evidence(self.state)

    def test_typed_dispatch_requires_top_role(self) -> None:
        """A selected native role cannot use the role-less metadata exception."""
        self.arguments["agent_type"] = "worker"
        self.spawn["agent_role"] = "worker"
        self.metadata.pop("agent_role")
        self._reject()

    def test_typed_dispatch_cannot_downgrade_child_role(self) -> None:
        """Reject an untyped child of an explicitly typed spawn."""
        self.arguments["agent_type"] = "loop-worker"
        self._reject()

    def test_duplicate_activity_including_wrong_path_rejected(self) -> None:
        """Reject duplicate activities even when one has a foreign path."""
        for path in (self.activity["agent_path"], "/root/other"):
            with self.subTest(path=path):
                self.extra_parent = [{"type": "event_msg", "payload": {"item": {**self.activity, "agent_path": path}}}]
                self._reject()

    def test_duplicate_call_including_wrong_role_rejected(self) -> None:
        """Reject duplicate calls even when one declares a different role."""
        for role in (None, "explorer"):
            with self.subTest(role=role):
                arguments = self.arguments if role is None else {**self.arguments, "agent_type": role}
                self.extra_parent = [
                    {"type": "response_item", "payload": {**self.call, "arguments": json.dumps(arguments)}}
                ]
                self._reject()

    def test_aborted_and_duplicate_completion_rejected(self) -> None:
        """Require one successful final completion."""
        self.terminal = "turn_aborted"
        self._reject()
        self.terminal = "task_complete"
        self.extra_child = [
            {
                "timestamp": "2026-09-21T00:00:04Z",
                "type": "event_msg",
                "payload": {"type": "task_complete", "turn_id": "turn"},
            }
        ]
        self._reject()

    def test_unfinished_followup_rejects_binding_and_revalidation(self) -> None:
        """An earlier success cannot attest a worker whose next turn is running."""
        reference = self._bind()
        self.extra_child = [
            {
                "timestamp": "2026-09-21T00:00:04Z",
                "type": "event_msg",
                "payload": {"type": "task_started", "turn_id": "followup"},
            }
        ]
        self._reject()
        self.state["graph"]["nodes"]["U3[1]"].update(status="done", evidence=[reference])
        self.state["graph"]["active_wave"] = None
        self._write_transcripts()
        with self.assertRaises(GraphError):
            validate_worker_evidence(self.state)

    def test_finished_followup_binds_its_own_terminal(self) -> None:
        """A completed follow-up replaces the earlier terminal identity."""
        self.extra_child = [
            {
                "timestamp": f"2026-09-21T00:00:0{index}Z",
                "type": "event_msg",
                "payload": {"type": event, "turn_id": "followup"},
            }
            for index, event in ((4, "task_started"), (5, "task_complete"))
        ]
        reference = self._bind()
        self.assertEqual(reference["task_complete_turn_id"], "followup")
        self.state["graph"]["nodes"]["U3[1]"].update(status="done", evidence=[reference])
        self.state["graph"]["active_wave"] = None
        validate_worker_evidence(self.state)

    def test_out_of_order_followup_completion_rejected(self) -> None:
        """A completion cannot precede its own native start event."""
        self.extra_child = [
            {
                "timestamp": f"2026-09-21T00:00:0{index}Z",
                "type": "event_msg",
                "payload": {"type": event, "turn_id": "followup"},
            }
            for index, event in ((4, "task_complete"), (5, "task_started"))
        ]
        self._reject()

    def test_reused_reference_rejected(self) -> None:
        """Prevent stored evidence from being reused by another node."""
        reference = self._bind()
        self.state["graph"]["nodes"]["U3[2]"] = {
            "retry": {"attempts": 0},
            "respawn": {"generation": 0},
            "status": "done",
            "evidence": [reference],
        }
        self._reject()


if __name__ == "__main__":
    unittest.main()
