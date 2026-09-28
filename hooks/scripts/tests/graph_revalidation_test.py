"""Preserve completion-time rechecks after genuine native evidence has been bound."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_evidence_revalidate import revalidate_all
from hooks.scripts.lib.graph_executor import graph_semantics, transition
from hooks.scripts.tests.claude_graph_test_support import (
    GraphCase,
    dispatch,
    fixture,
    load,
    read_records,
    write_records,
)


class RevalidationTests(GraphCase):
    """Start from working native evidence, then change only the asserted trust boundary."""

    def test_stored_provenance_shapes_and_missing_history(self) -> None:
        """Wrapped/serialized/partial/deleted native references never qualify as work."""
        state = self.finish()
        dispatch.validate_graph_completion(self.path, "fixture-session")
        reference = state["graph"]["nodes"]["U3[1]"]["evidence"][-1]
        shapes = [
            [],
            [[reference]],
            [{"note": {"inner": reference}}],
            [json.dumps(reference)],
            [{**reference, "kind": "claude_agent "}],
            [{**reference, "kind": "claude_аgent"}],
            [{"spawn_ref": reference["tool_use_id"], "attempt": 1}],
            ["worker finished, dispatch was toolu_ABC123"],
        ]
        for evidence in shapes:
            with self.subTest(evidence=evidence):
                variant = copy.deepcopy(state)
                variant["graph"]["nodes"]["U3[1]"]["evidence"] = evidence
                self.save(variant)
                self.refuse_completion()
        for history in (
            None,
            {},
            {"wave-2": {"cursor": 999, "nodes": ["U3[1]"], "revision": 2}},
            {"wave-2": {"cursor": 1, "nodes": ["U3[2]"], "revision": 2}},
        ):
            variant = copy.deepcopy(state)
            variant["graph"]["wave_history"] = history
            self.save(variant)
            self.refuse_completion("wave")

    def test_each_raw_reference_field_revalidates(self) -> None:
        """Real UUID, role, identity, ownership and attempt sequence remain authoritative."""
        state = self.finish()
        for key, value in (
            ("tool_use_id", "forged"),
            ("agent_id", "foreign"),
            ("record_uuid", "forged"),
            ("subagent_type", "Plan"),
            ("wave_id", "wave-99"),
            ("attempt", 2),
            ("outcome", "stale"),
        ):
            variant = copy.deepcopy(state)
            variant["graph"]["nodes"]["U3[1]"]["evidence"][-1][key] = value
            self.save(variant)
            self.refuse_completion()
        for status in ("done", "skipped"):
            variant = copy.deepcopy(state)
            variant["graph"]["nodes"]["U3[1]"].update(status=status, outcome=status, evidence=[])
            self.save(variant)
            self.refuse_completion("attempt history")

    def test_transcript_deletion_mutation_and_terminal_reversal(self) -> None:
        """Keeping a notification cannot compensate for deleted or changed spawn ownership."""
        self.finish()
        original = read_records(self.parent)
        mutations = [[], [record for record in original if record.get("type") != "assistant"]]
        for key, value in (("session_id", "foreign"), ("loop_id", "foreign"), ("node_id", "U3[2]")):
            altered = copy.deepcopy(original)
            request = altered[1]["message"]["content"][0]["input"]
            first, body = request["prompt"].split("\n", 1)
            owner = json.loads(first.split("=", 1)[1])
            owner[key] = value
            request["prompt"] = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(owner) + "\n" + body
            mutations.append(altered)
        altered = copy.deepcopy(original)
        altered[2]["toolUseResult"]["status"] = "teammate_spawned"
        mutations.append(altered)
        for records in mutations:
            write_records(self.parent, records)
            self.refuse_completion()
        write_records(self.parent, original)
        last = copy.deepcopy(original[-1])
        last["content"] = last["content"].replace("<status>completed</status>", "<status>failed</status>")
        fixture.append(self.parent, last)
        self.refuse_completion("completed notification")
        self.parent.write_text("not json\n")
        self.refuse_completion("transcript")

    def test_retry_and_stale_attempt_deletion_and_order(self) -> None:
        """All failed and abandoned attempts survive into the successful final audit."""
        self.finish("failed")
        self.finish("stale")
        transition(self.path, lambda state: graph_semantics.respawn_stale(state, "U3[1]", "verified idle")["state"])
        state = self.finish()
        dispatch.validate_graph_completion(self.path, "fixture-session")
        refs = [
            cast(dict[str, Any], entry)
            for entry in state["graph"]["nodes"]["U3[1]"]["evidence"]
            if isinstance(entry, dict)
        ]
        self.assertEqual([entry["attempt"] for entry in refs], [1, 2, 3])
        for attempt in (1, 2):
            variant = copy.deepcopy(state)
            variant["graph"]["nodes"]["U3[1]"]["evidence"] = [item for item in refs if item["attempt"] != attempt]
            self.save(variant)
            self.refuse_completion("attempt history")
        self.save(state)
        original = read_records(self.parent)
        for ref in refs[:-1]:
            altered = [record for record in original if ref["tool_use_id"] not in json.dumps(record)]
            write_records(self.parent, altered)
            self.refuse_completion("spawn|cursor")
        write_records(self.parent, original)
        variant = copy.deepcopy(state)
        variant["graph"]["nodes"]["U3[1]"]["respawn"]["generation"] += 1
        variant["graph"]["nodes"]["U3[1]"]["respawn"]["intent"]["generation"] += 1
        self.save(variant)
        self.refuse_completion("attempt history")

    def test_cross_node_reuse_cannot_hide_in_nonterminal_donor(self) -> None:
        """Revalidation binds IDs to their own node even outside completion eligibility."""
        self.save(fixture.state(2))
        state = self.finish()
        first = state["graph"]["nodes"]["U3[1]"]["evidence"][-1]
        second = state["graph"]["nodes"]["U3[2]"]["evidence"][-1]
        for evidence in ([first], [{"note": first}], [[first]]):
            variant = copy.deepcopy(state)
            variant["graph"]["nodes"]["U3[2]"]["evidence"] = evidence
            with self.assertRaises(ValueError):
                revalidate_all(variant)
        for status in ("done", "skipped"):
            variant = copy.deepcopy(state)
            variant["graph"]["nodes"]["U3[1]"].update(status=status, outcome=status, evidence=[second])
            variant["graph"]["nodes"]["U3[2]"].update(status="pending", outcome="pending", evidence=[])
            with self.assertRaisesRegex(ValueError, "another node"):
                revalidate_all(variant)
        variant = copy.deepcopy(state)
        variant["graph"]["nodes"]["U3[2]"]["evidence"] = []
        self.save(variant)
        self.refuse_completion("U3\\[2\\].*attempt history")

    def test_current_skipped_native_work_revalidates(self) -> None:
        """A skipped native attempt is owned without requiring a successful terminal."""
        state = self.finish("skipped")
        dispatch.validate_graph_completion(self.path, "fixture-session")
        ref = state["graph"]["nodes"]["U3[1]"]["evidence"][-1]
        records = read_records(self.parent)
        self.assertEqual(ref["outcome"], "skipped")
        write_records(self.parent, [record for record in records if ref["tool_use_id"] not in json.dumps(record)])
        self.refuse_completion("spawn")

    def test_completed_child_requires_a_real_terminal_message(self) -> None:
        """Harness notification and attribution cannot replace an actual child final."""
        state = self.opened()
        _, agent = fixture.spawn(self.parent, state, "U3[1]")
        child = self.parent.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"
        original = read_records(child)
        mutations: list[list[dict[str, Any]]] = []
        for content, stop in (
            ([], "end_turn"),
            ([{"type": "text", "text": ""}], "end_turn"),
            ([{"type": "text", "text": "working"}], "tool_use"),
            ([{"type": "text", "text": "partial"}], "max_tokens"),
        ):
            altered = copy.deepcopy(original)
            altered[-1]["message"].update(content=content, stop_reason=stop)
            mutations.append(altered)
        altered = copy.deepcopy(original)
        del altered[-1]["message"]
        mutations.append(altered)
        for entries in mutations:
            with self.subTest(entries=entries):
                self.save(state)
                write_records(child, entries)
                self.refuse_report(fixture.report(state), "terminal|completed")

    def test_failed_launch_requires_actual_native_error_result(self) -> None:
        """An explicit harness failed launch may retry; absent native authority cannot."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        original = read_records(self.parent)
        for entries in (
            original[:2],
            [
                *original[:2],
                {
                    "type": "user",
                    "sessionId": "fixture-session",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": original[2]["message"]["content"][0]["tool_use_id"],
                                "is_error": False,
                            }
                        ]
                    },
                },
            ],
        ):
            write_records(self.parent, entries)
            self.refuse_report(fixture.report(state, "failed"), "child identity")
        failed = copy.deepcopy(original[2])
        del failed["toolUseResult"]
        failed["message"]["content"][0].update(is_error=True, content="Native dispatch refused")
        write_records(self.parent, [*original[:2], failed])
        dispatch.record_wave(self.path, fixture.report(state, "failed"))
        self.assertEqual(load(self.path)["graph"]["nodes"]["U3[1]"]["retry"]["attempts"], 1)

    def test_missing_native_child_on_abandoned_work_is_refused(self) -> None:
        """A stale declaration cannot invent an attempt from a launch without a child."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", completed=False)
        original = read_records(self.parent)
        del original[2]["toolUseResult"]["agentId"]
        write_records(self.parent, original)
        self.refuse_report(fixture.report(state, "stale"), "child identity")


if __name__ == "__main__":
    unittest.main()
