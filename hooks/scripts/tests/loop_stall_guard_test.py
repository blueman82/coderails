#!/usr/bin/env python3
"""Exercise native Stop lifecycle counters and completion gates with explicit v3 fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.loop_evals import EvalStatus, EvalVerdict
from hooks.scripts.lib.loop_state_common import LoopState, count_invocations
from hooks.scripts.loop_stall_guard import complete
from hooks.scripts.tests.lib.hook_test_support import HookTestCase
from scripts.lib import proof_results as pr
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
        graph: dict[str, Any] = dict(nodes={}, edges=[], joins={}, active_wave=None, hard_stop=None, wave_history={})
        path = self.progress(graph=graph, proof_disposition="none: no executable surface", work_units={})
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

    def test_complete_matches_on_eval_verdict_status(self) -> None:
        """complete() branches on EvalVerdict.status and renders tamper_code as a field."""
        path = self.complete_fixture()
        state = LoopState(path, self.session, 1, json.loads(path.read_text()))
        base = "hooks.scripts.loop_stall_guard."
        with patch(base + "validate_completion", return_value=[]), patch(base + "validate_graph_completion"):
            for verdict, fragment in (
                (EvalVerdict(EvalStatus.TAMPERED, "x"), "TAMPERED:x"),
                (EvalVerdict(EvalStatus.FROZEN), "FROZEN"),
            ):
                with (
                    patch(base + "read_loop_evals", return_value=verdict),
                    self.assertRaisesRegex(ValueError, fragment),
                ):
                    complete(state, "unused")
            with patch(base + "read_loop_evals", return_value=EvalVerdict(EvalStatus.GO)):
                self.assertEqual(complete(state, "unused"), [])

    def test_skips_and_recorded_categories(self) -> None:
        """Non-loop/recursive stops pass; only a recorded same-revision row authorizes release, never text."""
        self.assertEqual(self.run_hook("loop_stall_guard", {}).returncode, 0)
        payload = self.payload(self.transcript("text", 0))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.progress()
        for text in ("text", "LOOP-STOP: paused", "LOOP-STOP: hard-stop — reason", "LOOP-STOP: complete"):
            payload = self.payload(self.transcript(text))
            result = self.run_hook("loop_stall_guard", payload)
            self.assertEqual(result.returncode, 2, text)
            self.assertIn("graph.py stop --category", result.stderr)
            self.assertNotIn("LOOP-STOP:", result.stderr)  # the message names the command, not a text line
        self.assertEqual(self.trace_reasons(), ["stop_row_missing"] * 4)
        payload["stop_hook_active"] = True
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        for category in ("hard-stop", "approval-gate", "awaiting-input"):
            self.progress(stops=[self.stop(1, category)])
            payload = self.payload(self.stopped(""))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0, category)

    def test_counters_accumulate_preserve_fields_and_consume_newest_first(self) -> None:
        """The sole atomic writer increments exactly one key per consumed row and preserves unrelated state."""
        rows = [self.stop(1, "hard-stop"), self.stop(2, "awaiting-input")]
        path = self.progress(custom_field={"nested": [1, 2, 3]}, stops=rows)
        before = json.loads(path.read_text())
        payload = self.payload(self.stopped(""))
        for expected in ({"awaiting-input": 1}, {"awaiting-input": 1, "hard-stop": 1}):
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
            self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], expected)
        after = json.loads(path.read_text())
        for key in ("loop_stop_counts", "updated_at", "stops"):
            self.assertIn(key, after)
            after.pop(key)
        before.pop("stops")
        self.assertEqual(after, before)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)  # both rows consumed: no free pass

    def trace_reasons(self) -> list[str]:
        """Return the non-authoritative trace reason codes written for this session."""
        path = self.directory / "state" / self.session / "trace.jsonl"
        rows = path.read_text().splitlines() if path.is_file() else []
        return [value["reason_code"] for row in rows if (value := json.loads(row)).get("command") == "loop_stall_guard"]

    def test_text_is_only_a_rendering_the_row_decides(self) -> None:
        """Matrix scenario: conflicting text releases as the row's category; the same text with no row blocks."""
        text = "LOOP-STOP: complete - x\nLOOP-STOP: hard-stop inline"
        path = self.complete_fixture()
        self.arm(path, self.stop(1, "complete"))
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(self.stopped(text))).returncode, 0)
        after = json.loads(path.read_text())
        self.assertEqual(after["loop_stop_counts"], {"complete": 1})  # complete() validation ran and counted
        self.assertTrue(after["stops"][0]["consumed"])
        self.assertEqual(self.trace_reasons(), [])
        self.arm(path)  # no row at all: the identical text must block
        before = path.read_text()
        result = self.run_hook("loop_stall_guard", self.payload(self.transcript(text)))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_text(), before)
        self.assertEqual(self.trace_reasons(), ["stop_row_missing"])

    def arm(self, path: Path, *rows: dict[str, Any]) -> None:
        """Replace the stops array (counters stay), as a fresh `graph.py stop` would."""
        data = json.loads(path.read_text())
        data["stops"] = list(rows)
        path.write_text(json.dumps(data))

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
        prompt = {"type": "user", "timestamp": "2033-05-18T03:33:21Z", "message": {"content": "carry on"}}
        old.write_text(old.read_text() + json.dumps(prompt) + "\n")
        chat = {"type": "assistant", "message": {"content": [{"type": "text", "text": "just chatting"}]}}
        old.write_text(old.read_text() + json.dumps(chat) + "\n")
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(old)).returncode, 2)
        after = json.loads(path.read_text())
        self.assertFalse(after["stops"][0]["consumed"])
        self.assertNotIn("loop_stop_counts", after)
        self.assertIn("stale_stop_row", self.trace_reasons())

    def test_stop_row_is_bound_to_the_turn_by_time_not_by_command_text(self) -> None:
        """Mentioning graph.py stop never releases an older row; a row recorded after the prompt does."""
        path = self.progress(stops=[self.stop(1, "awaiting-input", at=1.0e9)])
        trace = self.transcript("working")
        for record in (
            {"type": "user", "timestamp": "2033-05-18T03:33:21Z", "message": {"content": "next"}},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "echo graph.py stop"}}]
                },
            },
        ):
            trace.write_text(trace.read_text() + json.dumps(record) + "\n")
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(trace)).returncode, 2)
        self.assertFalse(json.loads(path.read_text())["stops"][0]["consumed"])
        self.arm(path, self.stop(2, "awaiting-input", at=2.0e9 + 2.0e9))
        self.assertEqual(self.run_hook("loop_stall_guard", self.payload(trace)).returncode, 0)

    def test_timestamp_less_new_user_prompt_cannot_release_old_row(self) -> None:
        """A prompt with no timestamp makes the turn boundary unknown and blocks an older stop."""
        path = self.progress(stops=[self.stop(1, "awaiting-input", at=2.0e9)])
        trace = self.stopped("")
        later = {"type": "user", "message": {"content": "continue"}}
        trace.write_text(trace.read_text() + json.dumps(later) + "\n")
        result = self.run_hook("loop_stall_guard", self.payload(trace))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(json.loads(path.read_text())["stops"][0]["consumed"])

    @staticmethod
    def stop(seq: int, category: str, revision: int = 1, consumed: bool = False, at: float = 1.0e9) -> dict[str, Any]:
        """Build one recorded stop row exactly as graph.py stop writes it."""
        return {
            "seq": seq,
            "category": category,
            "reason_code": "other",
            "reason": "r",
            "revision": revision,
            "consumed": consumed,
            "at": at,
        }

    def test_recorded_stop_decides_the_category_and_is_consumed_once(self) -> None:
        """A recorded stop decides the category, is consumed with the count, and never double-counts."""
        path = self.progress(stops=[self.stop(1, "approval-gate")])
        payload = self.payload(self.stopped("LOOP-STOP: hard-stop — conflicting text"))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        after = json.loads(path.read_text())
        self.assertEqual(after["loop_stop_counts"], {"approval-gate": 1})
        self.assertTrue(after["stops"][0]["consumed"])
        self.assertEqual(self.trace_reasons(), [])
        # repeated Stop: the row is consumed and the text is not read, so it blocks
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"approval-gate": 1})
        self.assertEqual(self.trace_reasons(), ["stop_row_missing"])

    def test_stale_or_torn_stops_never_release_even_with_a_text_declaration(self) -> None:
        """A stale-revision row, a consumed row, and malformed stops keys never fail the hook or release a Stop."""
        declared = self.payload(self.stopped("LOOP-STOP: awaiting-input — x"))
        stale, spent = self.stop(1, "hard-stop", revision=0), self.stop(1, "hard-stop", consumed=True)
        for stops in ([stale], [spent], "torn", [1, None]):
            path = self.progress(stops=stops)
            self.assertEqual(self.run_hook("loop_stall_guard", declared).returncode, 2)
            self.assertNotIn("loop_stop_counts", json.loads(path.read_text()))

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
        """Absent/corrupt state blocks and is never rewritten; a failed consume write cannot release Stop."""
        payload = self.payload(self.stopped("LOOP-STOP: hard-stop"))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        fabricated = [p.name for p in (self.directory / "state").rglob("*") if p.is_file() and p.name != "trace.jsonl"]
        self.assertEqual(fabricated, [])  # only trace rows may appear, never state
        path = self.progress()
        for contents in ("{malformed", '{"loop_stop_counts":"wrong"}'):
            path.write_text(contents)
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
            self.assertEqual(path.read_text(), contents)
        self.progress(stops=[self.stop(1, "hard-stop")])
        lock = Path(str(path) + ".lock")
        lock.mkdir()
        before = path.read_bytes()
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        self.assertEqual(path.read_bytes(), before)
        lock.rmdir()
        path.parent.chmod(0o555)
        try:
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
            self.assertFalse(list(path.parent.glob("*.tmp")))
        finally:
            path.parent.chmod(0o755)

    def test_slash_skill_registration_and_malformed_lines(self) -> None:
        """Only command-string slash tags count; quoted array text does not register loops."""
        path = self.progress(stops=[self.stop(n, "hard-stop") for n in (1, 2, 3)])
        trace = self.stopped("")
        final = trace.read_text().splitlines()[-1]
        for command in ("/agentic-loop", "/coderails:agentic-loop", "/coderails:agentic-loop   "):
            content = f"<command-name>/coderails:prep</command-name>\n<command-name>{command}</command-name>"
            trace.write_text(
                json.dumps({"type": "user", "timestamp": "2000-01-01T00:00:00Z", "message": {"content": content}})
                + "\n42\n{torn\n"
                + final
            )
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
        payload = self.payload(self.stopped(""))
        retro = path.with_name("retro.json")
        original = json.loads(retro.read_text())
        for contents in (None, "{bad", "[]", "{}", '{"schema_version":0}', '{"schema_version":"2"}'):
            self.arm(path, self.stop(1, "complete"))
            if contents is None:
                retro.unlink(missing_ok=True)
            else:
                retro.write_text(contents)
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
            self.assertNotIn("loop_stop_counts", json.loads(path.read_text()))
            self.assertFalse(json.loads(path.read_text())["stops"][0]["consumed"])
        for version in (1, 2, 99):
            self.arm(path, self.stop(1, "complete"))
            retro.write_text(json.dumps({**original, "schema_version": version}))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"complete": 3})

    def test_completion_identity_proof_eval_and_legacy_refusals(self) -> None:
        """Exact identity and frozen grade remain mandatory even with no unfinished graph nodes."""
        path = self.complete_fixture()
        payload = self.payload(self.stopped(""))
        row = self.stop(1, "complete")
        self.arm(path, row)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)  # the baseline really releases
        for filename, key, value in (
            ("retro.json", "session_id", "foreign"),
            ("evals.json", "revision", 2),
            ("evals.json", "result", None),
        ):
            self.arm(path, row)
            target = path.with_name(filename)
            original = target.read_text()
            target.write_text(json.dumps({**json.loads(original), key: value}))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
            target.write_text(original)
        original = path.read_text()
        for version in (1, 2):
            path.write_text(json.dumps({**json.loads(original), "schema_version": version, "stops": [row]}))
            self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        path.write_text(original)
        self.arm(path, row)
        proof = path.with_name("proof.json")
        document: dict[str, Any] = {"schema_version": 1, "session_id": self.session, "loop_id": "loop-test"}
        document["proofs"] = [{"id": "P1", "cmd": "unrun"}]
        proof.write_text(json.dumps(document))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        self.assertEqual(json.loads(path.read_text())["loop_stop_counts"], {"complete": 1})  # only the baseline run

    def test_controller_run_row_releases_the_stall_guard_without_a_transcript_call(self) -> None:
        """A satisfied proof_results row releases `complete` though the transcript has no matching Bash call."""
        path = self.complete_fixture()
        cmd = "python3 never_called_in_transcript.py"
        document = {
            "schema_version": 2,
            "session_id": self.session,
            "loop_id": "loop-test",
            "proofs": [{"id": "P1", "cmd": cmd, "expect": {"exit_code": 0}}],
        }
        path.with_name("proof.json").write_text(json.dumps(document))
        self.arm(path, self.stop(1, "complete"))
        payload = self.payload(self.stopped("LOOP-STOP: complete"))
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        results = path.with_name(pr.RESULTS_NAME)
        identity = {"session_id": self.session, "loop_id": "loop-test"}
        pr.append(results, kind="freeze", proof_json_sha256=pr.doc_sha(document), **identity)
        run = {
            "proof_id": "P1",
            "cmd_sha256": pr.sha(cmd),
            "proof_json_sha256": pr.doc_sha(document),
            "verdict": "satisfied",
            "cwd": str(Path.cwd()),
            "head_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "source_tree_sha": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
        }
        pr.append(results, kind="run", **run, **identity)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)

    def test_shared_absent_grace_and_complete_off_switch(self) -> None:
        """Only matching absent-state grace releases; existing active state stays policed."""
        payload = self.payload(self.transcript("no declaration"))
        log = self.directory / "discipline.log"
        log.write_text("hook=loop_state_guard session=S1 invocations=1 reason=absent blocked=1\n")
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)  # a forged log line releases nothing
        self.assertEqual(self.run_hook("loop_state_guard", payload).returncode, 2)  # the real block records the ordinal
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)  # shared hook_state.json releases
        self.progress()
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)
        self.progress("complete", 1)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 0)
        self.progress("complete", 0)
        self.assertEqual(self.run_hook("loop_stall_guard", payload).returncode, 2)


if __name__ == "__main__":
    unittest.main()
