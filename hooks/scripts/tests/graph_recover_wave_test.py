"""Claude recover-wave: one locked save, bounded by retry.max, never recording a node without a native spawn."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_recovery
from hooks.scripts.lib.graph_executor import graph_semantics
from hooks.scripts.tests.claude_graph_test_support import (
    GraphCase,
    dispatch,
    fixture,
    load,
    read_records,
    write_records,
)

LEASE = 600
STALLED = 1_789_948_802.0 + LEASE  # the fixture child's last record is 2026-09-21T00:00:02Z
UNITS = ("U3[1]", "U3[2]")
SESSION = "fixture-session"


class RecoverWaveTests(GraphCase):
    """Drive begin-wave, stalled children, recover-wave, re-dispatch and completion through real validators."""

    def setUp(self) -> None:
        """Two nodes, each allowed two recoveries."""
        super().setUp()
        state = fixture.state(2)
        for item in state["graph"]["nodes"].values():
            item["retry"]["max"] = 2
        self.save(state)

    def recover(self, now: float = STALLED, session: str = SESSION, apply: bool = True) -> dict[str, Any]:
        """Run recovery."""
        return dispatch.recover_wave(self.path, session, LEASE, now=now, apply=apply)

    def spawn_all(self, completed: bool = False) -> list[tuple[str, str]]:
        """Spawn every active node's current attempt."""
        state = load(self.path)
        return [
            fixture.spawn(self.parent, state, unit, completed=completed)
            for unit in state["graph"]["active_wave"]["nodes"]
        ]

    def cycle(self) -> None:
        """Dispatch a wave, stall it, recover it."""
        dispatch.begin_wave(self.path)
        self.spawn_all()
        self.assertTrue(self.recover()["recovered"])

    def trace(self) -> list[dict[str, Any]]:
        """Read the advisory sidecar."""
        sidecar = self.path.with_name("recovery-trace.jsonl")
        return [json.loads(line) for line in sidecar.read_text().splitlines()] if sidecar.is_file() else []

    def test_all_stalled_nodes_are_recovered_then_redispatched_and_completed(self) -> None:
        """Recovery, a2 dispatch, done and completion revalidation all succeed; a late a1 finish is harmless."""
        dispatch.begin_wave(self.path)
        first = self.spawn_all()
        report = self.recover()
        self.assertEqual((report["recovered"], report["reason_code"]), (True, "recovered"))
        state = load(self.path)
        self.assertIsNone(state["graph"]["active_wave"])
        self.assertEqual(state["graph"]["nodes"]["U3[1]"]["respawn"]["generation"], 1)
        self.assertEqual(state["graph"]["nodes"]["U3[1]"]["retry"]["attempts"], 0)
        self.finish_late(first)
        state = self.finish()
        dispatch.validate_graph_completion(self.path, SESSION)
        refs = [cast(dict[str, Any], e) for e in state["graph"]["nodes"]["U3[1]"]["evidence"] if isinstance(e, dict)]
        self.assertEqual([(e["attempt"], e["outcome"]) for e in refs], [(1, "stale"), (2, "done")])

    def finish_late(self, spawned: list[tuple[str, str]]) -> None:
        """Make every spawned worker finish: a terminal child record plus its completion notification."""
        for tool, agent in spawned:
            child = self.parent.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"
            fixture.append(
                child,
                {
                    "sessionId": SESSION,
                    "isSidechain": True,
                    "agentId": agent,
                    "type": "assistant",
                    "attributionAgent": "general-purpose",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "late"}],
                        "stop_reason": "end_turn",
                    },
                },
            )
            fixture.notify(self.parent, tool, agent)

    def test_a_worker_finishing_after_classification_is_never_recorded_stale(self) -> None:
        """The recheck under the lock sees the finish that landed after the unlocked classification."""
        dispatch.begin_wave(self.path)
        spawned = self.spawn_all()
        before = self.path.read_bytes()
        real, calls = graph_recovery.classify, cast("list[int]", [])

        def finishing(*args: object) -> dict[str, str]:
            result = real(*cast("tuple[Any, float, int]", args))
            if not calls:  # the worker finishes between the unlocked classify and the lock
                calls.append(1)
                self.finish_late(spawned)
            return result

        with patch.object(graph_recovery, "classify", side_effect=finishing), self.assertRaises(ValueError) as refused:
            self.recover()
        self.assertEqual(getattr(refused.exception, "reason_code", None), "mixed_wave")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.trace()[-1]["node_action"], None)
        self.assertEqual({r["node_id"] for r in self.trace() if r["reason_code"] == "mixed_wave"}, set(UNITS))

    def test_trace_tolerates_absent_graph_and_takes_a_command(self) -> None:
        """A refusal on a missing or corrupt state still writes a row, under the calling command."""
        graph_recovery.trace(self.path, {}, "refused", "start_refused_path", {"session": "s"}, [], command="start")
        row = self.trace()[-1]
        self.assertEqual(
            (row["command"], row["reason_code"], row["caller_session"]), ("start", "start_refused_path", "s")
        )
        self.assertIsNone(row["wave_id"])

    def test_trace_attempt_comes_from_the_locked_state_not_the_stale_pre_read(self) -> None:
        """A competing writer bumping respawn.generation after the unlocked read must show in the row."""
        dispatch.begin_wave(self.path)
        self.spawn_all()
        real = graph_recovery.classify
        calls: list[int] = []

        def bumping(*args: object) -> dict[str, str]:
            result = real(*cast("tuple[Any, float, int]", args))
            if not calls:
                calls.append(1)
                state = load(self.path)
                state["graph"]["nodes"]["U3[1]"]["respawn"]["generation"] = 1
                self.path.write_text(json.dumps(state))
            return result

        with patch.object(graph_recovery, "classify", side_effect=bumping):
            self.assertTrue(self.recover()["recovered"])
        rows = {r["node_id"]: r["attempt"] for r in self.trace() if r["reason_code"] == "recovered"}
        self.assertEqual(rows["U3[1]"], 2)

    def test_refusal_trace_attempt_comes_from_the_locked_state_not_the_stale_pre_read(self) -> None:
        """A writer that bumps respawn.generation and finishes a worker before the lock must show in the refusal row."""
        dispatch.begin_wave(self.path)
        spawned = self.spawn_all()
        real = graph_recovery.classify
        calls: list[int] = []

        def racing(*args: object) -> dict[str, str]:
            result = real(*cast("tuple[Any, float, int]", args))
            if not calls:
                calls.append(1)
                state = load(self.path)
                state["graph"]["nodes"]["U3[1]"]["respawn"]["generation"] = 1
                self.path.write_text(json.dumps(state))
                self.finish_late(spawned)
            return result

        with patch.object(graph_recovery, "classify", side_effect=racing), self.assertRaises(ValueError):
            self.recover()
        locked = load(self.path)
        refused = [r for r in self.trace() if r["outcome"] == "refused"]
        self.assertEqual({r["reason_code"] for r in refused}, {"mixed_wave"})
        for row in refused:
            node = locked["graph"]["nodes"][row["node_id"]]
            self.assertEqual(row["attempt"], node["retry"]["attempts"] + node["respawn"]["generation"] + 1)
            self.assertEqual(row["revision"], locked["revision"])
        self.assertEqual(len([r for r in refused if r["node_id"] == "U3[1]"]), 1)
        self.assertEqual(len({r["event_id"] for r in refused}), 1)  # one refusal event, traced once, many rows

    def test_trace_rows_are_timestamped_and_name_each_nodes_action(self) -> None:
        """An on-call can tell the finished node from the live one, and when it was recorded."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=True)
        fixture.spawn(self.parent, state, "U3[2]", completed=False)
        self.recover()
        rows = self.trace()
        self.assertEqual({r["node_id"]: r["node_action"] for r in rows}, {"U3[1]": "record", "U3[2]": "stalled"})
        self.assertRegex(rows[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")

    def test_refusal_rows_name_the_node_and_the_callers_session(self) -> None:
        """Budget, unreadable-transcript and foreign-session rows keep their who and which."""
        self.cycle()
        self.cycle()
        dispatch.begin_wave(self.path)
        spawned = self.spawn_all()
        with self.assertRaises(ValueError):
            self.recover()
        budget = [r for r in self.trace() if r["reason_code"] == "recovery_budget_exhausted"]
        self.assertEqual(({r["node_id"] for r in budget}, budget[0]["attempt"]), (set(UNITS), 3))
        child = self.parent.with_suffix("") / "subagents" / f"agent-{spawned[1][1]}.jsonl"
        write_records(child, [])
        with self.assertRaises(ValueError):
            self.recover(apply=False)
        unreadable = self.trace()[-1]
        self.assertEqual((unreadable["reason_code"], unreadable["node_id"]), ("unreadable_transcript", "U3[2]"))
        with self.assertRaises(ValueError):
            self.recover(session="other")
        foreign = self.trace()[-1]
        self.assertEqual((foreign["caller_session"], foreign["session_id"]), ("other", SESSION))

    def test_a_refusal_shows_its_reason_code_to_the_operator(self) -> None:
        """The CLI error text carries the stable code, not just the sidecar."""
        dispatch.begin_wave(self.path)
        with self.assertRaises(ValueError) as refused:
            self.recover(session="other")
        self.assertIn("[reason_code=foreign_session]", str(refused.exception))

    def test_no_spawn_node_is_reported_never_recorded_and_a_late_spawn_completes(self) -> None:
        """A node with no native spawn changes nothing; spawning it late records and completes normally."""
        dispatch.begin_wave(self.path)
        before = self.path.read_bytes()
        report = self.recover()
        self.assertEqual((report["recovered"], report["reason_code"]), (False, "no_spawn_dispatch"))
        self.assertEqual(self.path.read_bytes(), before)
        self.spawn_all(completed=True)
        dispatch.record_wave(self.path, fixture.report(load(self.path)))
        dispatch.validate_graph_completion(self.path, SESSION)

    def test_non_positive_lease_is_refused_and_changes_nothing(self) -> None:
        """A zero or negative lease would mark every live worker stalled, so it is refused before any read."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        before = self.path.read_bytes()
        for lease in (0, -5):
            with self.assertRaises(graph_recovery.RecoveryRefusedError) as raised:
                dispatch.recover_wave(self.path, SESSION, lease, now=STALLED)
            self.assertEqual(raised.exception.reason_code, "invalid_lease")
        self.assertEqual(self.path.read_bytes(), before)

    def test_within_lease_and_mixed_waves_change_nothing(self) -> None:
        """A waiting worker, or one finished sibling, blocks recovery without touching state."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        fixture.spawn(self.parent, state, "U3[2]", completed=True)
        before = self.path.read_bytes()
        report = self.recover()
        self.assertEqual((report["nodes"]["U3[2]"]["action"], report["reason_code"]), ("record", "mixed_wave"))
        self.assertEqual(self.recover(now=STALLED - 1)["nodes"]["U3[1]"]["action"], "waiting")
        self.assertEqual(self.path.read_bytes(), before)

    def test_recovery_is_bounded_by_the_retry_max(self) -> None:
        """The third recovery of a max-2 node refuses with its own code and changes nothing."""
        self.cycle()
        self.cycle()
        dispatch.begin_wave(self.path)
        self.spawn_all()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "recovery budget") as refused:
            self.recover()
        self.assertEqual(getattr(refused.exception, "reason_code", None), "recovery_budget_exhausted")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.trace()[-1]["reason_code"], "recovery_budget_exhausted")
        self.assertIn("recovery budget exhausted", graph_recovery.summarize(load(self.path))["detail"])

    def test_a_crash_between_node_transitions_leaves_state_untouched(self) -> None:
        """Record and every respawn are one save: a failure on the second respawn writes nothing."""
        dispatch.begin_wave(self.path)
        self.spawn_all()
        before = self.path.read_bytes()
        real = graph_semantics.respawn_stale
        calls: list[int] = []

        def flaky(state: dict[str, Any], node: str, reason: str) -> dict[str, Any]:
            if calls:
                raise ValueError("crash between node transitions")
            calls.append(1)
            return real(state, node, reason)

        with patch.object(graph_semantics, "respawn_stale", side_effect=flaky), self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(self.path.read_bytes(), before)

    def test_second_recovery_of_the_same_wave_does_not_double_generation(self) -> None:
        """The competing call finds no active wave and refuses."""
        self.cycle()
        with self.assertRaisesRegex(ValueError, "no active wave") as refused:
            self.recover()
        self.assertEqual(getattr(refused.exception, "reason_code", None), "no_active_wave")
        self.assertEqual(load(self.path)["graph"]["nodes"]["U3[1]"]["respawn"]["generation"], 1)

    def test_foreign_session_is_refused_with_a_code(self) -> None:
        """A session that does not own the loop is refused and traced."""
        dispatch.begin_wave(self.path)
        with self.assertRaises(ValueError) as refused:
            self.recover(session="other")
        self.assertEqual(getattr(refused.exception, "reason_code", None), "foreign_session")
        self.assertEqual([r["reason_code"] for r in self.trace()], ["foreign_session"])

    def test_unreadable_children_are_refused(self) -> None:
        """An empty child, a foreign child and a timestamp-less child each refuse classification."""
        dispatch.begin_wave(self.path)
        spawned = self.spawn_all()
        child = self.parent.with_suffix("") / "subagents" / f"agent-{spawned[0][1]}.jsonl"
        original = read_records(child)
        variants: list[list[dict[str, Any]]] = [
            [],
            [{**original[0], "sessionId": "other"}],
            [{k: v for k, v in original[0].items() if k != "timestamp"}],
        ]
        for variant in variants:
            write_records(child, variant)
            with self.assertRaises(ValueError) as refused:
                self.recover(apply=False)
            self.assertEqual(getattr(refused.exception, "reason_code", None), "unreadable_transcript")

    def test_trace_rows_are_closed_schema_and_failure_fails_open(self) -> None:
        """Each recovered node leaves one row; an unwritable sidecar never alters the transition."""
        dispatch.begin_wave(self.path)
        self.spawn_all()
        self.assertTrue(self.recover()["recovered"])
        rows = self.trace()
        self.assertEqual([r["node_id"] for r in rows], list(UNITS))
        self.assertEqual(
            set(rows[0]),
            {
                "schema_version", "event_id", "ts", "session_id", "caller_session", "loop_id", "wave_id", "node_id",
                "attempt",
                "node_action", "revision", "command", "outcome", "reason_code", "inputs_sha256",
            },
        )  # fmt: skip
        self.path.with_name("recovery-trace.jsonl").unlink()
        self.path.with_name("recovery-trace.jsonl").mkdir()
        self.assertTrue(self.cycle_after_recovery()["recovered"])

    def cycle_after_recovery(self) -> dict[str, Any]:
        """Open the next wave and recover it while the sidecar is unwritable."""
        dispatch.begin_wave(self.path)
        self.spawn_all()
        return self.recover()

    def test_summarize_names_the_phase(self) -> None:
        """Plain-language status derives from graph state alone."""
        self.assertEqual(graph_recovery.summarize(load(self.path))["phase"], "ready to dispatch")
        self.opened()
        self.assertEqual(graph_recovery.summarize(load(self.path))["phase"], "waiting for worker")


if __name__ == "__main__":
    unittest.main()
