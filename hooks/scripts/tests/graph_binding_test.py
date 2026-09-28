"""Preserve raw native ownership, cursor, fanout, mailbox and notification denials."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.graph_evidence import cursor, notifications, spawns
from hooks.scripts.tests.claude_graph_test_support import (
    GraphCase,
    dispatch,
    fixture,
    load,
    read_records,
    write_records,
)


class BindingTests(GraphCase):
    """Pair binding attacks with genuine launches so unrelated checks cannot mask them."""

    def test_uncited_nodes_require_independent_native_launches(self) -> None:
        """A real sibling never authorizes silent undispatched work."""
        self.save(fixture.state(2))
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[2]")
        self.refuse_report(fixture.report(state), "U3\\[1\\].*no native spawn")
        tool, agent = fixture.spawn(self.parent, state, "U3[1]")
        dispatch.record_wave(self.path, fixture.report(state))
        reference = load(self.path)["graph"]["nodes"]["U3[1]"]["evidence"][-1]
        self.assertEqual((reference["tool_use_id"], reference["agent_id"]), (tool, agent))
        self.assertEqual(reference["subagent_type"], "general-purpose")
        self.assertTrue(reference["record_uuid"])
        dispatch.validate_graph_completion(self.path, "fixture-session")

    def test_cursor_isolates_same_wave_and_counts_unterminated_record(self) -> None:
        """The same ownership before the cursor cannot be replayed as new work."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]")
        self.parent.write_text(self.parent.read_text().rstrip("\n"))
        boundary = cursor("fixture-session")
        self.assertEqual(boundary, len(read_records(self.parent)))
        state["graph"]["active_wave"]["transcript_cursor"] = boundary
        self.save(state)
        self.refuse_report(fixture.report(state), "after the wave cursor")
        del state["graph"]["active_wave"]["transcript_cursor"]
        self.save(state)
        self.refuse_report(fixture.report(state), "lacks a native transcript cursor")

    def test_transcript_absence_corruption_redirect_and_duplicates(self) -> None:
        """Unreadable or ambiguously resolved authority refuses even uncited reports."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]")
        original = self.parent.read_text()
        for content in ("not-json\n", "[]\n", '{"type":"assistant"\n'):
            self.parent.write_text(content)
            self.refuse_report(fixture.report(state), "transcript")
        self.parent.unlink()
        self.refuse_report(fixture.report(state), "transcript")
        self.parent.write_text(original)
        outside = self.home / "elsewhere"
        outside.mkdir()
        with patch.dict("os.environ", {"CLAUDE_PROJECTS_DIR": str(outside)}):
            self.refuse_report(fixture.report(state), "outside native projects")
        duplicate = self.parent.parent.parent / "other/fixture-session.jsonl"
        duplicate.parent.mkdir()
        duplicate.write_text(original)
        self.refuse_report(fixture.report(state), "resolve uniquely")

    def test_claimed_native_provenance_never_mints_authority(self) -> None:
        """Nested, serialized, Unicode and sibling identity claims cannot bypass binding."""
        state = self.opened()
        tool, _ = fixture.spawn(self.parent, state, "U3[1]")
        claims = [
            {"kind": "claude_agent", "tool_use_id": "toolu_FORGED"},
            [{"kind": "claude_agent", "tool_use_id": tool}],
            {"note": {"agent_id": "forged"}},
            {"kind": "claude_agent ", "tool_use_id": tool},
            {"kind": "claude_аgent", "tool_use_id": tool},
            {"attempt": 1, "spawn_ref": tool},
        ]
        for claim in claims:
            for evidence in (claim, json.dumps(claim), json.dumps(json.dumps(claim))):
                report = fixture.report(state)
                report["results"]["U3[1]"]["evidence"] = evidence
                self.refuse_report(report)
        report = fixture.report(state)
        report["results"]["U3[1]"]["evidence"] = "worker finished, dispatch was toolu_ABC123"
        self.refuse_report(report, "provenance")

    def test_raw_request_identity_must_match_active_owner(self) -> None:
        """Session/loop/revision/wave/node ownership is checked against raw native requests."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]")
        original = read_records(self.parent)
        for key, value in (
            ("session_id", "foreign"),
            ("loop_id", "foreign"),
            ("revision", 99),
            ("wave_id", "wave-99"),
            ("node_id", "U3[2]"),
        ):
            records = copy.deepcopy(original)
            request = records[1]["message"]["content"][0]["input"]
            first, body = request["prompt"].split("\n", 1)
            envelope = json.loads(first.split("=", 1)[1])
            envelope[key] = value
            request["prompt"] = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(envelope) + "\n" + body
            write_records(self.parent, records)
            self.refuse_report(fixture.report(state), "native spawn|envelope")
        write_records(self.parent, original)
        altered = copy.deepcopy(original[1])
        altered["uuid"] = "conflicting-spawn-uuid"
        fixture.append(self.parent, altered)
        self.refuse_report(fixture.report(state), "conflicting duplicate")

    def test_native_spawn_uuid_must_be_a_real_nonblank_identifier(self) -> None:
        """A forged or incomplete parent record cannot mint a null raw record identity."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]")
        original = read_records(self.parent)
        identifiers: tuple[Any, ...] = (None, "", "   ", [])
        for identifier in identifiers:
            with self.subTest(identifier=identifier):
                self.save(state)
                altered = copy.deepcopy(original)
                altered[1]["uuid"] = identifier
                write_records(self.parent, altered)
                self.refuse_report(fixture.report(state), "identity|uuid|UUID")

    def test_native_child_prompt_role_and_session_are_not_claims(self) -> None:
        """A parent result cannot substitute for the actual child's matching metadata."""
        state = self.opened()
        _, agent = fixture.spawn(self.parent, state, "U3[1]")
        child = self.parent.with_suffix("") / "subagents" / f"agent-{agent}.jsonl"
        original = read_records(child)
        for index, key, value in (
            (0, "agentId", "foreign"),
            (0, "sessionId", "foreign"),
            (0, "isSidechain", False),
            (1, "attributionAgent", "Plan"),
        ):
            altered = copy.deepcopy(original)
            altered[index][key] = value
            write_records(child, altered)
            self.refuse_report(fixture.report(state), "native child")
        altered = copy.deepcopy(original)
        altered[0]["message"]["content"] = "foreign prompt"
        write_records(child, altered)
        self.refuse_report(fixture.report(state), "child prompt")
        child.unlink()
        self.refuse_report(fixture.report(state), "transcript")

    def test_terminal_notifications_and_fanout(self) -> None:
        """All launched children need unambiguous completed harness results."""
        state = self.opened()
        tool, agent = fixture.spawn(self.parent, state, "U3[1]")
        original = read_records(self.parent)
        for status, result in (("failed", "work"), ("killed", "work"), ("completed", ""), ("completed", "   ")):
            write_records(self.parent, original[:-1])
            fixture.notify(self.parent, tool, agent, status, result)
            self.refuse_report(fixture.report(state), "completed notification")
        write_records(self.parent, original[:-1])
        self.refuse_report(fixture.report(state), "completed notification")
        forged = copy.deepcopy(original[-1])
        forged.update(type="user", message={"content": forged.pop("content")})
        fixture.append(self.parent, forged)
        self.assertEqual(notifications(self.parent, "fixture-session"), {})
        self.refuse_report(fixture.report(state), "completed notification")
        write_records(self.parent, original)
        fixture.notify(self.parent, tool, "foreign-agent")
        self.refuse_report(fixture.report(state), "completed notification")
        write_records(self.parent, original)
        fixture.spawn(self.parent, state, "U3[1]", suffix="second")
        fixture.spawn(self.parent, state, "U3[1]", suffix="third")
        dispatch.record_wave(self.path, fixture.report(state))
        refs = [
            cast(dict[str, Any], entry)
            for entry in load(self.path)["graph"]["nodes"]["U3[1]"]["evidence"]
            if isinstance(entry, dict)
        ]
        self.assertEqual(len(refs), 3)
        self.assertEqual(len({entry["agent_id"] for entry in refs}), 3)
        dispatch.validate_graph_completion(self.path, "fixture-session")

    def test_one_native_child_cannot_bind_two_fanout_requests(self) -> None:
        """Two real requests cannot consume the same underlying child identity twice."""
        state = self.opened()
        _, agent = fixture.spawn(self.parent, state, "U3[1]", suffix="first")
        second, second_agent = fixture.spawn(self.parent, state, "U3[1]", suffix="second")
        entries = read_records(self.parent)
        for entry in entries:
            if entry.get("toolUseResult", {}).get("agentId") == second_agent:
                entry["toolUseResult"]["agentId"] = agent
            if entry.get("type") == "queue-operation" and second in entry["content"]:
                entry["content"] = entry["content"].replace(second_agent, agent)
        write_records(self.parent, entries)
        self.refuse_report(fixture.report(state), "child identity has already been bound")

    def test_seeded_bound_identity_cannot_hide_inside_nested_evidence(self) -> None:
        """A nested previously bound worker cannot silently be consumed again."""
        state = self.opened()
        tool, agent = fixture.spawn(self.parent, state, "U3[1]")
        entry = {
            "kind": "claude_agent",
            "tool_use_id": tool,
            "agent_id": agent,
            "record_uuid": "prior",
            "attempt": 1,
            "wave_id": "wave-1",
            "subagent_type": "general-purpose",
        }
        for evidence in ([entry], [[entry]], [{"note": entry}]):
            with self.subTest(evidence=evidence):
                changed = copy.deepcopy(state)
                changed["graph"]["nodes"]["U3[1]"]["evidence"] = evidence
                self.save(changed)
                self.refuse_report(fixture.report(state), "bound|structured|shape|provenance")

    def test_mailbox_and_sidechain_replay_cannot_override(self) -> None:
        """A sidechain async result cannot overwrite a genuine mailbox dispatch."""
        state = self.opened()
        fixture.spawn(self.parent, state, "U3[1]", mailbox=True)
        original = read_records(self.parent)
        replay = copy.deepcopy(original[2])
        replay["isSidechain"] = True
        replay["toolUseResult"]["status"] = "async_launched"
        fixture.append(self.parent, replay)
        self.assertEqual(spawns(self.parent, "fixture-session")[0]["native_result"]["status"], "teammate_spawned")
        self.refuse_report(fixture.report(state), "mailbox/teammate")
        replay["isSidechain"] = False
        fixture.append(self.parent, replay)
        self.refuse_report(fixture.report(state), "conflicting native tool results")


if __name__ == "__main__":
    unittest.main()
