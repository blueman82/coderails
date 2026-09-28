"""Preserve exact waves, retries, stale checks, registry contracts and atomic writes."""

from __future__ import annotations

import copy
import json
import multiprocessing
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib import graph_executor
from hooks.scripts.lib.graph_executor import graph_semantics, ready_nodes, transition
from hooks.scripts.lib.loop_state_common import atomic_progress_update
from hooks.scripts.tests.claude_graph_test_support import GraphCase, dispatch, fixture, load


def concurrent_increment(path: str, key: str) -> None:
    """Widen the locked read/modify interval so competing writers truly overlap."""

    def update(state: dict[str, Any]) -> dict[str, Any]:
        """Retain every other writer's state while changing one counter."""
        previous = state.get(key, 0)
        time.sleep(0.08)
        state[key] = previous + 1
        return state

    transition(Path(path), update)


class TransitionTests(GraphCase):
    """Exercise the provider lock and current semantic adapter with real file state."""

    def test_schema_and_shape_refusals(self) -> None:
        """Retired schema and malformed nodes cannot reach readiness or mutate state."""
        baseline = fixture.state()
        variants: list[dict[str, Any]] = []
        for version in (None, 1, 2, "3"):
            variants.append({**baseline, "schema_version": version})
        for status in (None, ["done"], "merged", "failed"):
            state = copy.deepcopy(baseline)
            state["graph"]["nodes"]["U3[1]"].update(status=status, outcome=status)
            variants.append(state)
        for attempts, maximum in ((9, 5), (0, 99), (-3, 5), (0, 0), (True, 5)):
            state = copy.deepcopy(baseline)
            state["graph"]["nodes"]["U3[1]"]["retry"] = {"attempts": attempts, "max": maximum}
            variants.append(state)
        for state in variants:
            with self.subTest(state=state):
                self.save(state)
                original = self.path.read_bytes()
                with self.assertRaises((ValueError, TypeError)):
                    dispatch.begin_wave(self.path)
                self.assertEqual(original, self.path.read_bytes())
        self.path.write_text("not json")
        with self.assertRaisesRegex(ValueError, "cannot read"):
            ready_nodes(self.path)
        self.save(fixture.state(0))
        self.assertEqual(ready_nodes(self.path), [])

    def test_exact_wave_fields_and_collect_before_write(self) -> None:
        """Reject incomplete/extra/malformed reports and replace once for two results."""
        self.save(fixture.state(2))
        state = self.opened()
        for identifier in state["graph"]["active_wave"]["nodes"]:
            fixture.spawn(self.parent, state, identifier)
        report = fixture.report(state)
        malformed: list[dict[str, Any]] = [
            {**report, "extra": True},
            {**report, "wave_id": "wave-999"},
            {**report, "results": []},
            {**report, "results": {"U3[1]": report["results"]["U3[1]"]}},
            {**report, "results": {**report["results"], "UNKNOWN": {"outcome": "done", "evidence": "x"}}},
        ]
        bad_results: tuple[Any, ...] = (
            {},
            "clobbered",
            {"status": "done", "evidence": "x"},
            {"outcome": "done", "evidence": []},
            {"outcome": "done", "evidence": "x", "retry": {"attempts": 9, "max": 5}},
            {"outcome": "done", "status": None, "evidence": "x"},
        )
        for value in bad_results:
            variant = copy.deepcopy(report)
            variant["results"]["U3[1]"] = value
            malformed.append(variant)
        for variant in malformed:
            self.refuse_report(variant)
        with patch.object(graph_executor, "atomic_progress_update", wraps=atomic_progress_update) as update:
            dispatch.record_wave(self.path, report)
        self.assertEqual(update.call_count, 1)
        final = load(self.path)
        self.assertEqual(final["revision"], state["revision"] + 1)
        self.assertEqual(ready_nodes(self.path), [])
        self.assertTrue(
            all(item["status"] == "done" and item["retry"]["max"] == 5 for item in final["graph"]["nodes"].values())
        )
        self.refuse_report(report, "no active wave")

    def test_retry_exhaustion_keeps_sibling_result(self) -> None:
        """A failed worker retries exactly to its bound while retaining completed peers."""
        state = fixture.state(2)
        state["graph"]["nodes"]["U3[1]"]["retry"]["max"] = 2
        self.save(state)
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        fixture.spawn(self.parent, state, "U3[2]")
        report = fixture.report(state)
        report["results"]["U3[1]"]["outcome"] = "failed"
        dispatch.record_wave(self.path, report)
        self.assertEqual(ready_nodes(self.path), ["U3[1]"])
        state = self.finish("failed")
        self.assertEqual(state["graph"]["nodes"]["U3[1]"]["retry"]["attempts"], 2)
        self.assertEqual(state["graph"]["nodes"]["U3[1]"]["status"], "hard-stop")
        self.assertEqual(state["graph"]["nodes"]["U3[2]"]["status"], "done")
        self.assertEqual(ready_nodes(self.path), [])
        self.refuse_completion("hard_stop")

    def test_stale_requires_this_wave_check(self) -> None:
        """Bare idle and stale checks carried from earlier waves cannot mark stale."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        report = fixture.report(state, "stale")
        for check in (
            None,
            {},
            {"checked": False, "method": "inspect", "result": "idle"},
            {"checked": True, "method": "", "result": "idle"},
            {"checked": True, "method": "inspect"},
            {"checked": True, "method": "inspect", "result": "   "},
        ):
            invalid = copy.deepcopy(report)
            invalid["results"]["U3[1]"]["stale_check"] = check
            self.refuse_report(invalid, "stale_check")
        dispatch.record_wave(self.path, report)
        self.assertEqual(
            load(self.path)["graph"]["nodes"]["U3[1]"]["stale_check"], report["results"]["U3[1]"]["stale_check"]
        )
        transition(self.path, lambda value: graph_semantics.respawn_stale(value, "U3[1]", "checked idle")["state"])
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        report = fixture.report(state, "stale")
        del report["results"]["U3[1]"]["stale_check"]
        self.refuse_report(report, "stale_check")

    def test_two_process_writers_preserve_both_changes(self) -> None:
        """Actual concurrent lock contention cannot lose either writer's update."""
        context = multiprocessing.get_context("fork")
        workers = [context.Process(target=concurrent_increment, args=(str(self.path), key)) for key in ("a", "b")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(5)
            self.assertEqual(worker.exitcode, 0)
        state = json.loads(self.path.read_text())
        self.assertEqual((state["a"], state["b"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
