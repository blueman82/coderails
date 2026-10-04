"""Fail closed, with a stable reason code, on stored or dispatched node-only (pre-loop-scoped) task names."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "codex/skills/agentic-loop/scripts"))
import graph
from graph_evidence import validate_worker_evidence
from graph_identity import GraphError, is_legacy_task_name, task_node
from graph_recovery import RecoveryRefusedError

from packages.tests.codex_fixture import append, frozen_evals, node, read_json, spawn, state, transcripts, write_json

CODE = "legacy_task_identity_refused"
LEGACY = "loop_worker_55335b315d"  # node U3[1], attempt 1, no loop scope: a literal, no helper may mint it
LEGACY_A2 = LEGACY + "_a2"
LEGACY_U2 = "loop_worker_55335b325d"  # node U3[2]


def _spawn_records(task: str, call: str, child: str) -> list[dict[str, Any]]:
    """Return a native function_call and its SubAgentActivity for one spawn."""
    return [
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "spawn_agent",
                "namespace": "collaboration",
                "call_id": call,
                "arguments": json.dumps({"task_name": task}),
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "item": {
                    "type": "SubAgentActivity",
                    "kind": "started",
                    "id": call,
                    "agent_thread_id": child,
                    "agent_path": f"/root/{task}",
                }
            },
        },
    ]


def _child_records(child: str, task: str, turn: str) -> list[dict[str, Any]]:
    """Return the owned child transcript of one completed spawn."""
    spawned = {"parent_thread_id": "parent", "depth": 1, "agent_role": None, "agent_path": f"/root/{task}"}
    metadata = {
        "id": child,
        "parent_thread_id": "parent",
        "session_id": "parent",
        "thread_source": "subagent",
        "agent_role": None,
        "source": {"subagent": {"thread_spawn": spawned}},
    }
    return [
        {"timestamp": "2026-09-21T00:00:01Z", "type": "session_meta", "payload": metadata},
        {
            "timestamp": "2026-09-21T00:00:02Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": turn},
        },
        {
            "timestamp": "2026-09-21T00:00:03Z",
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": turn},
        },
    ]


def _reference(attempt: int, call: str, child: str, turn: str, wave: str) -> dict[str, Any]:
    """Return one stored codex_agent evidence reference."""
    return {
        "kind": "codex_agent",
        "attempt": attempt,
        "wave_id": wave,
        "spawn_call_id": call,
        "agent_thread_id": child,
        "task_complete_turn_id": turn,
    }


class LegacyTaskRefusalTests(unittest.TestCase):
    """Node-only historical names are refused, never silently bound or skipped."""

    def setUp(self) -> None:
        """Place native transcript fixtures under an isolated home directory."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.home).start()

    def _write(self, *attempts: tuple[str, str, str, str]) -> None:
        """Write a parent transcript and one child per (task, call, child, turn)."""
        sessions = self.home / ".codex/sessions"
        sessions.mkdir(parents=True)
        parent = sessions / "fixture-parent.jsonl"
        append(parent, {"type": "session_meta", "payload": {"id": "parent"}})
        for task, call, child, turn in attempts:
            for record in _spawn_records(task, call, child):
                append(parent, record)
            for record in _child_records(child, task, turn):
                append(sessions / f"fixture-{child}.jsonl", record)

    def _state(self, evidence: list[dict[str, Any]], attempts: int = 0, generation: int = 0) -> dict[str, Any]:
        """Return a graph state whose one node holds the given stored references."""
        return {
            "schema_version": 3,
            "session_id": "parent",
            "loop_id": "loop",
            "revision": 2 + 2 * len(evidence),
            "status": "in-progress",
            "graph": {
                "nodes": {
                    "U3[1]": {
                        "retry": {"attempts": attempts},
                        "respawn": {"generation": generation},
                        "status": "done" if evidence else "stale",
                        "evidence": evidence,
                    }
                },
                "joins": {},
                "active_wave": None,
            },
        }

    def _refused(self, value: dict[str, Any]) -> RecoveryRefusedError:
        """Assert validation refuses with the stable code and return the error."""
        with self.assertRaises(RecoveryRefusedError) as caught:
            validate_worker_evidence(value)
        self.assertEqual(caught.exception.reason_code, CODE)
        return caught.exception

    def test_stored_legacy_identity_is_refused(self) -> None:
        """A stored reference whose spawn carries a node-only name is refused with the stable code."""
        self._write((LEGACY, "call", "child", "turn"))
        value = self._state([_reference(1, "call", "child", "turn", "wave-1")])
        self.assertEqual(self._refused(value).nodes, ("U3[1]",))

    def test_legacy_stale_attempt_without_reference_is_refused(self) -> None:
        """A node-only stale spawn with no completion reference is refused, not skipped as unmatched."""
        self._write(
            (LEGACY, "call", "child", "turn"), ("loop_worker_6c6f6f70_55335b315d_a2", "call-2", "child-2", "t2")
        )
        value = self._state([_reference(2, "call-2", "child-2", "t2", "wave-3")], generation=1)
        value["revision"] = 4
        with self.assertRaises(RecoveryRefusedError) as caught:
            validate_worker_evidence(value)
        self.assertEqual(caught.exception.reason_code, CODE)
        self.assertIn("attempt 1 ", str(caught.exception))

    def test_legacy_retry_identity_is_refused_and_undecodable(self) -> None:
        """The retry-suffixed node-only spelling is refused too, and task_node no longer decodes any legacy name."""
        for name in (LEGACY, LEGACY_A2):
            self.assertTrue(is_legacy_task_name(name))
            with self.assertRaises(GraphError):
                task_node(name)
        self._write((LEGACY, "call", "child", "turn"), (LEGACY_A2, "call-2", "child-2", "turn-2"))
        references = [
            _reference(1, "call", "child", "turn", "wave-1"),
            _reference(2, "call-2", "child-2", "turn-2", "wave-3"),
        ]
        self._refused(self._state(references, attempts=1))

    def test_foreign_session_never_reaches_the_legacy_refusal(self) -> None:
        """A node-only spawn in another session's transcript is invisible: the caller gets a generic refusal."""
        self._write((LEGACY, "call", "child", "turn"))
        value = self._state([_reference(1, "call", "child", "turn", "wave-1")])
        value["session_id"] = "foreign"
        with self.assertRaises(GraphError) as caught:
            validate_worker_evidence(value)
        self.assertNotEqual(getattr(caught.exception, "reason_code", None), CODE)

    def test_loop_scoped_names_are_not_legacy_shaped(self) -> None:
        """Negative control: canonical names, including retries, never match the legacy shape."""
        for name in ("loop_worker_6c6f6f70_55335b315d", "loop_worker_6c6f6f70_55335b315d_a2", "worker_55335b315d"):
            self.assertFalse(is_legacy_task_name(name))
        self.assertEqual(task_node("loop_worker_6c6f6f70_55335b315d_a2"), ("loop", "U3[1]"))

    def test_legacy_identity_cannot_authorize_fresh_dispatch(self) -> None:
        """A node-only historical task name cannot authorize a new loop dispatch."""
        value = self._state([])
        value["graph"]["nodes"]["U3[1]"]["status"] = "running"
        value["graph"]["active_wave"] = {"wave_id": "wave-1", "revision": 2, "nodes": ["U3[1]"]}
        state_path = self.home / "progress.json"
        state_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(GraphError):
            graph.authorize_dispatch(state_path, "parent", LEGACY, self.home / "evals.json")


class LegacyRefusalTraceTests(unittest.TestCase):
    """record-wave over a stored node-only reference refuses, traces once, and leaves state untouched."""

    def setUp(self) -> None:
        """Build a live U3[1] wave beside a done U3[2] whose stored spawn carries a node-only name."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.addCleanup(patch.stopall)
        patch("pathlib.Path.home", return_value=self.directory).start()
        self.path = self.directory / "progress.json"
        initial = state()
        done = node(2, "done")
        done["evidence"] = [_reference(1, "legacy-call", "legacy-child", "legacy-turn", "wave-1")]
        initial["graph"]["nodes"]["U3[2]"] = done
        write_json(self.path, initial)
        write_json(self.path.with_name("evals.json"), frozen_evals())
        parent = transcripts(self.directory)
        wave = graph.begin_wave(self.path)
        spawn(parent, read_json(self.path), "U3[1]")
        for record in _spawn_records(LEGACY_U2, "legacy-call", "legacy-child"):
            append(parent, record)
        for record in _child_records("legacy-child", LEGACY_U2, "legacy-turn"):
            append(self.directory / ".codex/sessions/fixture-legacy-child.jsonl", record)
        envelope = {"wave_id": wave["wave_id"], "results": {"U3[1]": {"outcome": "done", "evidence": "ok"}}}
        self.results = json.dumps(envelope)

    def _rows(self) -> list[dict[str, Any]]:
        """Return the parsed trace rows."""
        trace = self.path.with_name("recovery-trace.jsonl")
        return [json.loads(line) for line in trace.read_text().splitlines()]

    def test_refusal_is_coded_traced_once_and_state_unchanged(self) -> None:
        """The refusal carries the code, one trace row names it, and progress.json is byte-identical."""
        before = self.path.read_bytes()
        with self.assertRaises(RecoveryRefusedError) as caught:
            graph.record_wave(self.path, self.results)
        self.assertEqual(caught.exception.reason_code, CODE)
        self.assertEqual(self.path.read_bytes(), before)
        rows = self._rows()
        self.assertEqual(
            [(r["command"], r["outcome"], r["reason_code"]) for r in rows], [("record-wave", "refused", CODE)]
        )
        self.assertEqual(rows[0]["session_id"], "parent")
        self.assertTrue(rows[0]["event_id"] and rows[0]["inputs_sha256"])

    def test_unwritable_trace_does_not_change_the_refusal(self) -> None:
        """Unwritable trace storage is fail-open: the same coded refusal and no extra exception."""
        self.path.with_name("recovery-trace.jsonl").mkdir()
        with self.assertRaises(RecoveryRefusedError) as caught:
            graph.record_wave(self.path, self.results)
        self.assertEqual(caught.exception.reason_code, CODE)

    def test_torn_trace_tail_does_not_change_the_refusal(self) -> None:
        """A half-written previous row is left alone and the refusal is unchanged."""
        self.path.with_name("recovery-trace.jsonl").write_text('{"event_id": "torn', encoding="utf-8")
        with self.assertRaises(RecoveryRefusedError) as caught:
            graph.record_wave(self.path, self.results)
        self.assertEqual(caught.exception.reason_code, CODE)


if __name__ == "__main__":
    unittest.main()
