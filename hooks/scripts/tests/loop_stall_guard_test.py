#!/usr/bin/env python3
"""Exercise native Stop lifecycle counters and completion gates with explicit v3 fixtures."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_state_common import count_invocations
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib.eval_artifact import grading_checksum


class StallGuardTests(HookTestCase):
    """Keep declared-stop release distinct from audited, identity-bound completion."""

    def setUp(self) -> None:
        """Use a native Claude home for graph transcript ownership validation."""
        super().setUp()
        self.environment["HOME"] = str(self.directory)
        self.environment["CLAUDE_PROJECTS_DIR"] = str(self.directory / ".claude/projects")

    def transcript(self, text: str = "", invocations: int = 1) -> Path:
        """Place fixture transcript under its actual native session filename."""
        temporary = super().transcript(text, invocations)
        path = self.directory / ".claude/projects/fixture" / f"{self.session}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(path)
        return path

    def complete_fixture(self) -> Path:
        """Create a zero-work current graph, explicit proof disposition, and graded artifacts."""
        graph: dict[str, Any] = {
            "nodes": {},
            "edges": [],
            "joins": {},
            "active_wave": None,
            "hard_stop": None,
            "wave_history": {},
        }
        path = self.progress(graph=graph, proof_disposition="none", work_units={})
        identity = {"session_id": self.session, "loop_id": "loop-test"}
        path.with_name("retro.json").write_text(json.dumps({"schema_version": 2, **identity}))
        suite_path = path.with_name("evals.json")
        suite: dict[str, Any] = {
            "scope": "loop",
            "result": "GO",
            "verification_level": 0,
            "verification_justification": "zero work fixture",
            "revision": 1,
            "evals": [],
            **identity,
        }
        suite_path.write_text(json.dumps(suite))
        suite["grading"] = {"by": "post_evals.py grade-loop", "checksum": grading_checksum(suite_path, "GO")}
        suite_path.write_text(json.dumps(suite))
        return path

    def test_skips_and_declared_categories(self) -> None:
        """Non-loop/recursive stops pass; only anchored vocabulary declarations authorize release."""
        self.assertEqual(self.run_hook("loop_stall_guard", {}).returncode, 0)
        payload = self.payload(self.transcript("text", 0))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.progress()
        for text in ("text", "LOOP-STOP: paused", "Quoted LOOP-STOP: hard-stop", "LOOP-STOP: completed"):
            payload = self.payload(self.transcript(text))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        payload["stop_hook_active"] = True
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        for category in ("hard-stop", "approval-gate", "awaiting-input", "HARD-STOP"):
            payload = self.payload(self.transcript("LOOP-STOP: " + category + " — reason"))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)

    def test_counters_accumulate_preserve_fields_and_use_last_category(self) -> None:
        """The sole atomic writer increments exactly one key and preserves unrelated state."""
        path = self.progress(custom_field={"nested": [1, 2, 3]})
        before = json.loads(path.read_text())
        payload = self.payload(self.transcript("LOOP-STOP: hard-stop\nLOOP-STOP: awaiting-input — last"))
        for count in (1, 2):
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
            after = json.loads(path.read_text())
            self.assertEqual(after.pop("loop_stop_counts"), {"awaiting-input": count})
            self.assertEqual(after, before)
        payload = self.payload(self.transcript("LOOP-STOP: approval-gate"))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"awaiting-input": 2, "approval-gate": 1})

    def trace_reasons(self) -> list[str]:
        """Return the non-authoritative trace reason codes written for this session."""
        path = self.directory / "state" / self.session / "trace.jsonl"
        rows = path.read_text().splitlines() if path.is_file() else []
        return [json.loads(row)["reason_code"] for row in rows]

    def test_inline_mention_never_flips_the_declared_category(self) -> None:
        """Only an anchored declaration line picks the category; a later inline mention is prose (H06)."""
        path = self.progress()
        text = "LOOP-STOP: awaiting-input — need a decision\nearlier I wrote LOOP-STOP: hard-stop inline"
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(self.transcript(text))).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"awaiting-input": 1})
        self.assertEqual(self.trace_reasons(), ["legacy_text_parse"])

    def stopped(self, text: str) -> Path:
        """Transcript whose current turn ran graph.py stop, as a real recorded stop would."""
        path = self.transcript(text)
        call = {"type": "tool_use", "name": "Bash", "input": {"command": "python3 graph.py stop --category x"}}
        row = {"type": "assistant", "message": {"content": [call]}}
        path.write_text(path.read_text() + json.dumps(row) + "\n")
        return path

    def test_stale_row_from_an_earlier_turn_never_releases(self) -> None:
        """A row recorded before the last user prompt is stale: chatting afterwards stays blocked (finding 1)."""
        path = self.progress(stops=[self.stop(1, "awaiting-input")])
        old = self.stopped("done")
        prompt = {"type": "user", "message": {"content": "carry on"}}
        old.write_text(old.read_text() + json.dumps(prompt) + "\n")
        chat = {"type": "assistant", "message": {"content": [{"type": "text", "text": "just chatting"}]}}
        old.write_text(old.read_text() + json.dumps(chat) + "\n")
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(old)).returncode, 2)
        self.assertEqual(
            self.run_hook("loop_stall_guard", self.payload(self.transcript("just chatting"))).returncode, 2
        )
        after = json.loads(path.read_text())
        self.assertFalse(after["stops"][0]["consumed"])
        self.assertNotIn("loop_stop_counts", after)
        self.assertIn("stale_stop_row", self.trace_reasons())

    @staticmethod
    def stop(seq: int, category: str, revision: int = 1, consumed: bool = False) -> dict[str, Any]:
        """Build one recorded stop row exactly as graph.py stop writes it."""
        return {
            "seq": seq,
            "category": category,
            "reason_code": "other",
            "reason": "r",
            "revision": revision,
            "consumed": consumed,
        }

    def test_recorded_stop_wins_over_text_and_is_consumed_once(self) -> None:
        """A recorded stop decides the category, is consumed with the count, and never double-counts."""
        path = self.progress(stops=[self.stop(1, "approval-gate")])
        payload = self.payload(self.stopped("LOOP-STOP: hard-stop — conflicting text"))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        after = json.loads(path.read_text())
        self.assertEqual(after["loop_stop_counts"], {"approval-gate": 1})
        self.assertTrue(after["stops"][0]["consumed"])
        self.assertEqual(self.trace_reasons(), [])
        # repeated Stop: the row is consumed, so the text path runs and its hard-stop is counted instead
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"approval-gate": 1, "hard-stop": 1})
        self.assertEqual(self.trace_reasons(), ["legacy_text_parse"])
        bare = self.payload(self.transcript("no declaration"))
        self.assertEqual(self.run_hook("loop_stall_guard", bare).returncode, 2)

    def test_stale_or_torn_stops_fall_back_to_text(self) -> None:
        """A stale-revision row, a consumed row, and malformed stops keys never fail the hook or release a Stop."""
        bare = self.payload(self.transcript("no declaration"))
        stale, spent = self.stop(1, "hard-stop", revision=0), self.stop(1, "hard-stop", consumed=True)
        for stops in ([stale], [spent], "torn", [1, None]):
            self.progress(stops=stops)
            self.assertEqual(self.run_hook("loop_stall_guard", bare).returncode, 2)
        path = self.progress(stops="torn")
        text = self.payload(self.transcript("LOOP-STOP: awaiting-input — x"))
        self.assertEqual(self.run_hook("loop_stall_guard", text).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"awaiting-input": 1})

    def test_recorded_complete_still_requires_a_resolved_graph(self) -> None:
        """A recorded complete stop is refused while the graph is unresolved and stays unconsumed."""
        graph: dict[str, Any] = {
            "nodes": {"S1": {"status": "pending"}},
            "edges": [],
            "joins": {},
            "active_wave": None,
            "hard_stop": None,
            "wave_history": {},
        }
        path = self.progress(graph=graph, stops=[self.stop(1, "complete")])
        bare = self.payload(self.transcript("no declaration"))
        self.assertEqual(self.run_hook("loop_stall_guard", bare).returncode, 2)
        after = json.loads(path.read_text())
        self.assertFalse(after["stops"][0]["consumed"])
        self.assertNotIn("loop_stop_counts", after)

    def test_counter_failure_never_fabricates_state_or_leaks_temporary_files(self) -> None:
        """Absent/corrupt/locked/unwritable state leaves declared-stop release advisory."""
        payload = self.payload(self.transcript("LOOP-STOP: hard-stop"))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.assertFalse((self.directory / "state").exists())
        path = self.progress()
        for contents in ("{malformed", '{"loop_stop_counts":"wrong"}'):
            path.write_text(contents)
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
            self.assertEqual(path.read_text(), contents)
        self.progress()
        lock = Path(str(path) + ".lock")
        lock.mkdir()
        before = path.read_bytes()
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.assertEqual(path.read_bytes(), before)
        lock.rmdir()
        path.parent.chmod(0o555)
        try:
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
            self.assertFalse(list(path.parent.glob("*.tmp")))
        finally:
            path.parent.chmod(0o755)

    def test_slash_skill_registration_and_malformed_lines(self) -> None:
        """Only command-string slash tags count; quoted array text does not register loops."""
        path = self.progress()
        trace = self.transcript("LOOP-STOP: hard-stop")
        final = trace.read_text().splitlines()[-1]
        for command in ("/agentic-loop", "/coderails:agentic-loop", "/coderails:agentic-loop   "):
            content = f"<command-name>/coderails:prep</command-name>\n<command-name>{command}</command-name>"
            trace.write_text(json.dumps({"type": "user", "message": {"content": content}}) + "\n42\n{torn\n" + final)
            self.assertEqual(count_invocations(str(trace))[0], 1)
            self.assertEqual(self.run_hook("loop_stall_guard", self.payload(trace)).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"]["hard-stop"], 3)
        trace.write_text(
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": [{"type": "text", "text": "<command-name>/agentic-loop</command-name>"}]},
                }
            )
        )
        self.assertEqual(count_invocations(str(trace))[0], 0)
        trace = self.transcript("no declaration")
        trace.write_text(trace.read_text() + "\n42\n{torn")
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(trace)).returncode, 2)

    def test_retro_schema_and_complete_counters(self) -> None:
        """Completion requires retro schema and only increments after all gates succeed."""
        path = self.complete_fixture()
        payload = self.payload(self.transcript("LOOP-STOP: Complete"))
        retro = path.with_name("retro.json")
        original = json.loads(retro.read_text())
        for contents in (None, "{bad", "[]", "{}", '{"schema_version":0}', '{"schema_version":"2"}'):
            if contents is None:
                retro.unlink(missing_ok=True)
            else:
                retro.write_text(contents)
            result = self.run_hook("loop_stall_guard", payload)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("loop_stop_counts", json.loads(path.read_text()))
        for version in (1, 2, 99):
            retro.write_text(json.dumps({**original, "schema_version": version}))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"Complete": 3})

    def test_completion_identity_proof_eval_and_legacy_refusals(self) -> None:
        """Exact identity and frozen grade remain mandatory even with no unfinished graph nodes."""
        path = self.complete_fixture()
        payload = self.payload(self.transcript("LOOP-STOP: complete"))
        for filename, key, value in (
            ("retro.json", "session_id", "foreign"),
            ("evals.json", "revision", 2),
            ("evals.json", "result", None),
        ):
            target = path.with_name(filename)
            original = target.read_text()
            target.write_text(json.dumps({**json.loads(original), key: value}))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
            target.write_text(original)
        original = path.read_text()
        for version in (1, 2):
            path.write_text(json.dumps({**json.loads(original), "schema_version": version}))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        path.write_text(original)
        proof = path.with_name("proof.json")
        proof.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "session_id": self.session,
                    "loop_id": "loop-test",
                    "proofs": [{"id": "P1", "cmd": "unrun"}],
                }
            )
        )
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        self.assertNotIn("loop_stop_counts", json.loads(path.read_text()))

    def test_shared_absent_grace_and_complete_off_switch(self) -> None:
        """Only matching absent-state grace releases; existing active state stays policed."""
        payload = self.payload(self.transcript("no declaration"))
        log = self.directory / "discipline.log"
        log.write_text("hook=loop_state_guard session=S1 invocations=1 reason=absent blocked=1\n")
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.progress()
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        self.progress("complete", 1)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.progress("complete", 0)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)


if __name__ == "__main__":
    unittest.main()
