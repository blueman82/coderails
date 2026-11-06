"""A justified scout skip releases its join without a fabricated worker spawn."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_evidence_bind import bind_wave
from hooks.scripts.lib.graph_evidence_revalidate import revalidate_all
from hooks.scripts.tests.claude_graph_test_support import GraphCase, dispatch, fixture, load, node


class ScoutSkipTests(GraphCase):
    """Check a whole Claude wave with two skipped scout stages."""

    def test_historical_native_fanout_revalidates(self) -> None:
        """Distinct children in one pre-contract attempt remain valid historical evidence."""
        state = load(self.path)
        state["revision"] = 2
        state["graph"]["contract_from_revision"] = 100
        state["graph"]["nodes"]["U3[1]"].update(status="running", outcome="running")
        state["graph"]["active_wave"] = {
            "wave_id": "wave-2",
            "revision": 2,
            "nodes": ["U3[1]"],
            "transcript_cursor": 1,
        }
        state["graph"]["wave_history"] = {"wave-2": {"cursor": 1, "nodes": ["U3[1]"], "revision": 2}}
        fixture.spawn(self.parent, state, "U3[1]", suffix="first")
        fixture.spawn(self.parent, state, "U3[1]", suffix="second")
        refs = bind_wave(state, {"U3[1]": {"outcome": "done", "evidence": "historical native fanout"}})["U3[1]"]
        self.assertEqual(len(refs), 2)
        state["graph"]["nodes"]["U3[1]"].update(status="done", outcome="done", evidence=refs)
        state["graph"]["active_wave"] = None
        state["revision"] = 3
        revalidate_all(state)

    def assert_approval_tamper_refused(
        self, state: dict[str, Any], rows: list[dict[str, Any]], request: str, save: Callable[[], None]
    ) -> None:
        """A changed reply, request, or next message invalidates approval."""
        rows[4]["message"]["content"] = "deny"
        save()
        with self.assertRaisesRegex(ValueError, "approval"):
            revalidate_all(state)
        rows[4]["message"]["content"] = "approve"
        rows[3]["message"]["content"][0]["text"] = request.replace("fixture-loop", "foreign-loop")
        save()
        with self.assertRaisesRegex(ValueError, "approval"):
            revalidate_all(state)
        rows[3]["message"]["content"][0]["text"] = request
        rows.insert(
            4,
            {
                "type": "assistant",
                "sessionId": "fixture-session",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "New"}, {"type": "text", "text": "question"}],
                },
            },
        )
        save()
        with self.assertRaisesRegex(ValueError, "approval"):
            revalidate_all(state)

    def assert_approved_wave_releases_join(self, state: dict[str, Any], evidence: str) -> None:
        """Record an approved skip with its other scout and check the join."""
        wave_state = copy.deepcopy(state)
        wave_state["revision"] = 3
        wave_state["graph"]["contract_from_revision"] = 3
        scout = wave_state["graph"]["nodes"]["S2.5"]
        scout.update(status="running", outcome="running", evidence=scout["evidence"][:1])
        wave_state["graph"]["nodes"]["S2.6"] = node("S2.6", "running")
        wave_state["graph"]["nodes"]["J2"] = node("J2")
        wave_state["graph"]["edges"] = [{"from": "S2.5", "to": "J2"}, {"from": "S2.6", "to": "J2"}]
        wave_state["graph"]["joins"] = {
            "J2": {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"], "released": False}
        }
        wave_state["graph"]["active_wave"] = {
            "wave_id": "wave-3",
            "revision": 3,
            "nodes": ["S2.5", "S2.6"],
            "transcript_cursor": 5,
        }
        wave_state["graph"]["wave_history"]["wave-3"]["nodes"] = ["S2.5", "S2.6"]
        self.save(wave_state)
        dispatch.record_wave(
            self.path,
            {
                "wave_id": "wave-3",
                "results": {
                    "S2.5": {"outcome": "skipped", "evidence": evidence},
                    "S2.6": {"outcome": "skipped", "evidence": "no_retired_path: no path is retired"},
                },
            },
        )
        recorded = load(self.path)
        self.assertEqual(recorded["graph"]["nodes"]["J2"]["status"], "done")
        self.assertEqual(recorded["graph"]["nodes"]["S2.5"]["status"], "skipped")

    def test_no_fork_and_no_retirement_release_join(self) -> None:
        """Two justified skips release their shared join."""
        state = load(self.path)
        state["graph"]["nodes"] = {
            "S2": node("S2", "done"),
            "S2.5": node("S2.5"),
            "S2.6": node("S2.6"),
            "J2": node("J2"),
        }
        state["graph"]["edges"] = [
            {"from": "S2", "to": "S2.5"},
            {"from": "S2", "to": "S2.6"},
            {"from": "S2.5", "to": "J2"},
            {"from": "S2.6", "to": "J2"},
        ]
        state["graph"]["joins"] = {"J2": {"id": "J2", "mode": "all", "inputs": ["S2.5", "S2.6"], "released": False}}
        self.save(state)
        opened = self.opened()
        wave = opened["graph"]["active_wave"]["wave_id"]
        dispatch.record_wave(
            self.path,
            {
                "wave_id": wave,
                "results": {
                    "S2.5": {"outcome": "skipped", "evidence": "no_design_fork: plan has no unresolved design fork"},
                    "S2.6": {"outcome": "skipped", "evidence": "no_retired_path: plan retires no existing path"},
                },
            },
        )
        result = load(self.path)
        self.assertEqual(result["graph"]["nodes"]["J2"]["status"], "done")
        self.assertEqual(result["graph"]["nodes"]["S2.5"]["status"], "skipped")
        native_only = copy.deepcopy(result)
        native_only["graph"]["nodes"].pop("S2")  # the setup node predates this fixture's native wave
        revalidate_all(native_only)
        native_only["graph"]["nodes"]["S2.5"]["evidence"][0] = "no_design_fork: altered reason"
        with self.assertRaisesRegex(ValueError, "reason"):
            revalidate_all(native_only)
        native_only["graph"]["nodes"]["S2.5"]["evidence"][0] = result["graph"]["nodes"]["S2.5"]["evidence"][0]
        native_only["graph"]["nodes"]["S2.5"]["evidence"][1]["attempt"] = True
        with self.assertRaisesRegex(ValueError, "invalid scout skip"):
            revalidate_all(native_only)
        native_only["graph"]["nodes"]["S2.5"]["evidence"][1]["attempt"] = 1
        native_only["graph"]["nodes"]["S2.5"]["evidence"].append(
            copy.deepcopy(native_only["graph"]["nodes"]["S2.5"]["evidence"][1])
        )
        with self.assertRaisesRegex(ValueError, "attempt history"):
            revalidate_all(native_only)

    def test_skip_cannot_replace_a_spawn(self) -> None:
        """An actual native scout spawn excludes a no-work skip."""
        state = load(self.path)
        state["graph"]["nodes"] = {"S2": node("S2", "done"), "S2.5": node("S2.5")}
        state["graph"]["edges"] = [{"from": "S2", "to": "S2.5"}]
        self.save(state)
        opened = self.opened()
        fixture.spawn(self.parent, opened, "S2.5", role="coderails:design-scout")
        self.refuse_report(
            {
                "wave_id": opened["graph"]["active_wave"]["wave_id"],
                "results": {"S2.5": {"outcome": "skipped", "evidence": "no_design_fork: false claim"}},
            },
            "cannot reuse a native spawn",
        )

    def test_non_independent_claim_without_native_approval_refuses(self) -> None:
        """A caller's approval claim cannot replace native approval evidence."""
        state = load(self.path)
        state["graph"]["nodes"] = {"S2": node("S2", "done"), "S2.5": node("S2.5")}
        state["graph"]["edges"] = [{"from": "S2", "to": "S2.5"}]
        self.save(state)
        opened = self.opened()
        self.refuse_report(
            {
                "wave_id": opened["graph"]["active_wave"]["wave_id"],
                "results": {
                    "S2.5": {"outcome": "skipped", "evidence": "non_independent: human approved"},
                },
            },
            "approval",
        )

    def test_approved_fallback_uses_direct_user_reply(self) -> None:
        """A prior refused scout and the next owner reply support a retry skip."""
        state = load(self.path)
        state["graph"]["nodes"] = {"S2.5": node("S2.5", "running")}
        scout = state["graph"]["nodes"]["S2.5"]
        scout["retry"]["attempts"] = 1
        scout["evidence"] = [
            {
                "kind": "claude_agent",
                "attempt": 1,
                "wave_id": "wave-1",
                "tool_use_id": "toolu_old",
                "record_uuid": "old-spawn",
                "subagent_type": "coderails:design-scout",
                "outcome": "failed",
            }
        ]
        state["graph"]["active_wave"] = {
            "wave_id": "wave-3",
            "revision": 3,
            "nodes": ["S2.5"],
            "transcript_cursor": 5,
        }
        state["graph"]["wave_history"] = {
            "wave-1": {"cursor": 1, "nodes": ["S2.5"], "revision": 1},
            "wave-3": {"cursor": 5, "nodes": ["S2.5"], "revision": 3},
        }
        state["graph"]["contract_from_revision"] = 100
        prompt = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(
            {
                "session_id": state["session_id"],
                "loop_id": state["loop_id"],
                "revision": 1,
                "wave_id": "wave-1",
                "node_id": "S2.5",
            }
        )
        request = (
            "Coderails: Approve a non-independent design-scout fallback for loop fixture-loop, "
            "node S2.5, attempt 2? Reply approve or deny."
        )
        rows: list[dict[str, Any]] = [
            {
                "type": "user",
                "sessionId": "fixture-session",
                "uuid": "initial",
                "message": {"role": "user", "content": "start"},
            },
            {
                "type": "assistant",
                "sessionId": "fixture-session",
                "uuid": "old-spawn",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Agent",
                            "id": "toolu_old",
                            "input": {"subagent_type": "coderails:design-scout", "prompt": prompt},
                        }
                    ]
                },
            },
            {
                "type": "user",
                "sessionId": "fixture-session",
                "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_old", "is_error": True}]},
                "toolUseResult": {"is_error": True},
            },
            {
                "type": "assistant",
                "sessionId": "fixture-session",
                "message": {"role": "assistant", "content": [{"type": "text", "text": request}]},
            },
            {"type": "user", "sessionId": "fixture-session", "message": {"role": "user", "content": "approve"}},
        ]

        def save() -> None:
            self.parent.write_text("".join(json.dumps(row) + "\n" for row in rows))

        save()
        evidence = "non_independent: human approved design fallback"
        result = {"S2.5": {"outcome": "skipped", "evidence": evidence}}
        ref = bind_wave(state, result)["S2.5"][0]
        self.assertEqual(ref["reason"], "non_independent")
        scout.update(status="skipped", outcome="skipped", evidence=[*scout["evidence"], evidence, ref])
        state["graph"]["active_wave"] = None
        revalidate_all(state)
        self.assert_approved_wave_releases_join(state, evidence)
        self.assert_approval_tamper_refused(state, rows, request, save)


if __name__ == "__main__":
    unittest.main()
