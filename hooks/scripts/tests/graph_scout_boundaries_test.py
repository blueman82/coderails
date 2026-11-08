"""Scout skips must establish absence and issue ownership before any durable release."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path
from typing import Any, cast

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.scout_native_fixture import NativeScoutFixture
from hooks.scripts.tests.lib.scout_skip_fixture import ScoutFixture


class ScoutBoundaryTests(unittest.TestCase):
    """Exercise public recording and production revalidation on synthetic provider inputs."""

    def fixture(self, provider: str) -> NativeScoutFixture:
        """Give each case independent state and native-shaped source files."""
        case = NativeScoutFixture(provider)
        self.addCleanup(case.close)
        return case

    def assert_saved_skip(self, case: ScoutFixture, report: dict[str, Any] | None = None) -> dict[str, Any]:
        """Require an accepted reasoned skip and two read-only production checks."""
        result = case.record(report)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = case.load()
        self.assertEqual(saved["graph"]["nodes"]["S2.5"]["status"], "skipped")
        self.assertEqual(saved["graph"]["nodes"]["S2.6"]["status"], "skipped")
        self.assertEqual(saved["graph"]["nodes"]["J2"]["status"], "done")
        for node_id in ("S2.5", "S2.6"):
            references = [
                cast(dict[str, Any], item)
                for item in saved["graph"]["nodes"][node_id]["evidence"]
                if isinstance(item, dict) and cast(dict[str, Any], item).get("kind") == "graph_skip"
            ]
            self.assertEqual(len(references), 1)
        before = case.path.read_bytes()
        for _ in range(2):
            verified = case.revalidate()
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(case.path.read_bytes(), before)
        return saved

    def assert_refused(self, case: ScoutFixture, report: dict[str, Any] | None = None, later: bool = False) -> None:
        """Refusal must preserve every state byte and the complete transcript."""
        before, transcript = case.path.read_bytes(), case.transcript.read_bytes()
        result = case.revalidate() if later else case.record(report)
        self.assertNotIn("ModuleNotFoundError", result.stderr)
        self.assertNotIn("SyntaxError", result.stderr)
        self.assertNotEqual(result.returncode, 0, f"invalid skip accepted: {result.stdout}")
        self.assertEqual(case.path.read_bytes(), before)
        self.assertEqual(case.transcript.read_bytes(), transcript)

    def mutate(self, state: dict[str, Any], node_id: str, change: str, later: bool) -> None:
        """Change one named relationship while leaving its paired fresh control intact."""
        graph = state["graph"]
        record_id, record = next((key, item) for key, item in graph["dispatches"].items() if item["node_id"] == node_id)
        wave_id = record["wave_id"]
        if change == "consumed":
            record["authorized"] = {"tool_use_id": "unused-native-call"}
        elif change == "missing-dispatch":
            del graph["dispatches"][record_id]
        elif change == "duplicate-dispatch":
            graph["dispatches"]["duplicate"] = copy.deepcopy(record)
        elif change == "wrong-node":
            record["node_id"] = "S2.6" if node_id == "S2.5" else "S2.5"
        elif change == "wrong-attempt":
            record["attempt"] = 2
        elif change == "wrong-revision":
            record["revision"] += 1
        elif change == "missing-history":
            graph.pop("wave_history")
        elif change == "empty-history":
            graph["wave_history"] = {}
        elif change == "missing-wave":
            del graph["wave_history"][wave_id]
        elif change == "cursor":
            if later:
                graph["wave_history"][wave_id]["cursor"] += 1
            else:
                graph["active_wave"]["transcript_cursor"] += 1

    def test_fresh_skips_and_ordinary_absent_history_remain_valid(self) -> None:
        """Fresh skip controls and undispatched ordinary states need no fabricated child."""
        for provider in ("claude", "codex"):
            case = self.fixture(provider)
            with self.subTest(provider=provider):
                self.assert_saved_skip(case)
                for empty in (False, True):
                    state = copy.deepcopy(case.initial)
                    if empty:
                        state["graph"]["wave_history"] = {}
                    case.save(state)
                    before = case.path.read_bytes()
                    result = case.run("inspect", str(case.path))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(case.path.read_bytes(), before)
                    self.assertEqual(case.load()["graph"]["nodes"]["J2"]["status"], "pending")

    def test_consumed_authorization_without_launch_refuses_before_save(self) -> None:
        """Accepted native authorization alone cannot become no-work skip evidence."""
        for provider in ("claude", "codex"):
            case = self.fixture(provider)
            for node_id in ("S2.5", "S2.6"):
                with self.subTest(provider=provider, node=node_id):
                    case.reset()
                    case.consume(node_id)
                    self.assertEqual(case.transcript.read_bytes(), case.initial_transcript)
                    self.assert_refused(case)

    def test_malformed_result_values_refuse_without_writes_or_tracebacks(self) -> None:
        """Input objects must be checked before evidence binding accesses their fields."""
        values: tuple[Any, ...] = ("clobbered", [], {}, {"outcome": "skipped", "evidence": []})
        for provider in ("claude", "codex"):
            case = self.fixture(provider)
            for value in values:
                with self.subTest(provider=provider, value=value):
                    case.reset()
                    report = case.report()
                    report["results"]["S2.5"] = value
                    before = case.path.read_bytes()
                    result = case.record(report)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(case.path.read_bytes(), before)

    def test_native_result_and_fresh_sibling_skip_remain_usable(self) -> None:
        """Consumed authorization for an actual child must remain valid native evidence."""
        for provider in ("claude", "codex"):
            for node_id, explicit_id in (("S2.5", True), ("S2.6", True), ("S2.5", False), ("S2.6", False)):
                with self.subTest(provider=provider, node=node_id, explicit_id=explicit_id):
                    case = self.fixture(provider)
                    if not explicit_id:
                        case.environment["CODERAILS_A6_EVIDENCE_WRITE"] = "off"
                    case.native_result(node_id)
                    report = case.report()
                    report["results"][node_id] = {
                        "outcome": "done",
                        "evidence": "Synthetic native scout completed",
                        "final_report": {
                            "claims": [
                                {
                                    "text": "Scout completed",
                                    "label": "verified",
                                    "source": "synthetic source-fixture terminal",
                                }
                            ],
                            "did_not_verify": [],
                        },
                    }
                    result = case.record(report)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    saved = case.load()
                    self.assertEqual(saved["graph"]["nodes"][node_id]["status"], "done")
                    self.assertEqual(saved["graph"]["nodes"]["J2"]["status"], "done")
                    before = case.path.read_bytes()
                    for _ in range(2):
                        result = case.revalidate()
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(case.path.read_bytes(), before)

    def test_unsupported_issue_or_history_refuses_before_save_and_at_reliance(self) -> None:
        """Missing, ambiguous, consumed or stale skip bindings cannot release a join."""
        changes = (
            "consumed",
            "missing-dispatch",
            "duplicate-dispatch",
            "wrong-node",
            "wrong-attempt",
            "wrong-revision",
            "missing-history",
            "empty-history",
            "missing-wave",
            "cursor",
        )
        for provider in ("claude", "codex"):
            case = self.fixture(provider)
            saved = self.assert_saved_skip(case)
            for later in (False, True):
                for node_id in ("S2.5", "S2.6"):
                    for change in changes:
                        with self.subTest(provider=provider, later=later, node=node_id, change=change):
                            case.reset()
                            state = copy.deepcopy(saved if later else case.baseline)
                            self.mutate(state, node_id, change, later)
                            case.save(state)
                            self.assert_refused(case, later=later)

    def test_codex_raw_scout_work_refuses_before_save_and_at_reliance(self) -> None:
        """Incomplete indexes cannot turn a raw scout call into proof of no work."""
        case = self.fixture("codex")
        saved = self.assert_saved_skip(case)
        for later in (False, True):
            for node_id in ("S2.5", "S2.6"):
                for kind in ("unresolved", "duplicate-activity", "other-attempt", "other-attempt-start"):
                    with self.subTest(later=later, node=node_id, kind=kind):
                        case.reset()
                        case.save(copy.deepcopy(saved if later else case.baseline))
                        case.raw_codex_call(node_id, kind)
                        self.assert_refused(case, later=later)

    def test_codex_unrelated_and_historical_raw_calls_do_not_prevent_a_skip(self) -> None:
        """The raw-request check must keep its loop/node and wave boundary scope."""
        case = self.fixture("codex")
        for historical in (False, True):
            with self.subTest(historical=historical):
                state = case.reset()
                case.raw_codex_call("S2.5", "unresolved", "different-loop" if not historical else "loop")
                if historical:
                    state["graph"]["active_wave"]["transcript_cursor"] = 2
                    state["graph"]["wave_history"]["wave-2"]["cursor"] = 2
                    case.save(state)
                self.assert_saved_skip(case)

    def test_prior_refusal_proof_at_recording_and_terminal_reliance(self) -> None:
        """A fallback must prove its preceding issue, exact try, request, result and approval."""
        changes = (
            "missing-issue",
            "duplicate-issue",
            "unused-auth",
            "null-id",
            "foreign-id",
            "malformed-auth",
            "bool-try",
            "float-try",
            "zero-try",
            "duplicate-reference",
            "missing-history",
            "old-cursor",
            "late-result",
            "duplicate-call",
            "duplicate-result",
            "missing-result",
            "approval-before-result",
            "request-before-result",
            "wrong-role",
            "missing-envelope",
            "foreign-envelope",
            "missing-sections",
            "success-result",
        )
        for provider in ("claude", "codex"):
            case = self.fixture(provider)
            report = case.fallback()
            pending, transcript = case.load(), case.transcript.read_bytes()
            saved = self.assert_saved_skip(case, report)
            for later in (False, True):
                for change in changes:
                    with self.subTest(provider=provider, later=later, change=change):
                        state = copy.deepcopy(saved if later else pending)
                        rows = [json.loads(line) for line in transcript.decode().splitlines()]
                        case.change_prior(state, rows, change)
                        case.save(state)
                        case.transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
                        self.assert_refused(case, report, later=later)

    def test_safe_prior_modes_and_approval_after_wave_issue(self) -> None:
        """ON and durable Codex OFF proofs remain usable on either side of issuance."""
        for provider in ("claude", "codex"):
            for after in (False, True):
                for mode in ("on", "off"):
                    with self.subTest(provider=provider, after=after, mode=mode):
                        case = self.fixture(provider)
                        if mode == "off" and provider == "codex":
                            case.environment["CODERAILS_GRAPH_DISPATCH"] = "off"
                        report = case.fallback(approval_after_issue=after)
                        if mode == "off":
                            case.environment["CODERAILS_GRAPH_DISPATCH"] = "off"
                        if mode == "off" and provider == "codex":
                            state = case.load()
                            rows = [json.loads(line) for line in case.transcript.read_text().splitlines()]
                            case.change_prior(state, rows, "wrong-role")
                            case.change_prior(state, rows, "missing-sections")
                            case.save(state)
                            case.transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
                        self.assert_saved_skip(case, report)

    def test_unbound_failure_audit_does_not_prove_fallback(self) -> None:
        """Ordinary refused-result history can survive without becoming strict skip proof."""
        for provider in ("claude", "codex"):
            for marker in ("unused", "null-id"):
                with self.subTest(provider=provider, marker=marker):
                    case = self.fixture(provider)
                    case.environment["CODERAILS_GRAPH_DISPATCH"] = "off"
                    case.refuse(authorize=False)
                    state = case.load()
                    self.assertEqual(state["graph"]["nodes"]["S2.5"]["retry"]["attempts"], 1)
                    if marker == "null-id":
                        next(record for record in state["graph"]["dispatches"].values() if record["node_id"] == "S2.5")[
                            "authorized"
                        ] = {"tool_use_id": None}
                        case.save(state)
                    case.approve()
                    case.opened = case.accept("begin-wave", str(case.path))
                    report = {
                        "wave_id": case.opened["wave_id"],
                        "results": {
                            "S2.5": {
                                "outcome": "skipped",
                                "evidence": "non_independent: human approved design fallback",
                            }
                        },
                    }
                    self.assert_refused(case, report)

    def test_claude_true_issued_try_cannot_be_relabelled(self) -> None:
        """A genuine consumed try2 cannot substantiate retained try1, even with coherent counters."""
        case = self.fixture("claude")
        case.refuse()
        case.opened = case.accept("begin-wave", str(case.path))
        case.refuse()
        state = case.load()
        ref = next(
            cast(dict[str, Any], item)
            for item in reversed(state["graph"]["nodes"]["S2.5"]["evidence"])
            if isinstance(item, dict)
        )
        ref["attempt"] = 1
        state["graph"]["nodes"]["S2.5"].update(evidence=["retained failure", ref])
        state["graph"]["nodes"]["S2.5"]["retry"]["attempts"] = 1
        case.save(state)
        case.approve()
        case.opened = case.accept("begin-wave", str(case.path))
        report = {
            "wave_id": case.opened["wave_id"],
            "results": {"S2.5": {"outcome": "skipped", "evidence": "non_independent: human approved design fallback"}},
        }
        self.assert_refused(case, report)

    def test_claude_foreign_prior_refusal_refuses_before_save_and_at_reliance(self) -> None:
        """A correct approval cannot authorize refusal history from a different loop or wave."""
        case = self.fixture("claude")
        report = case.fallback()
        fallback, transcript = case.load(), case.transcript.read_bytes()
        saved = self.assert_saved_skip(case, report)
        for later in (False, True):
            for change in ("loop", "raw-wave", "reference-wave"):
                with self.subTest(later=later, change=change):
                    case.transcript.write_bytes(transcript)
                    state = copy.deepcopy(saved if later else fallback)
                    rows = [json.loads(line) for line in transcript.decode().splitlines()]
                    if change == "reference-wave":
                        ref = state["graph"]["nodes"]["S2.5"]["evidence"][1]
                        self.assertEqual(ref["kind"], "claude_agent")
                        ref["wave_id"] = "wave-99"
                        state["graph"]["wave_history"]["wave-99"] = copy.deepcopy(
                            state["graph"]["wave_history"]["wave-2"]
                        )
                    else:
                        tool = rows[1]["message"]["content"][0]
                        prompt = tool["input"]["prompt"].split("\n", 1)
                        envelope = json.loads(prompt[0].split("=", 1)[1])
                        envelope["loop_id" if change == "loop" else "wave_id"] = (
                            "foreign-loop" if change == "loop" else "wave-99"
                        )
                        tool["input"]["prompt"] = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(envelope) + "\n" + prompt[1]
                    case.transcript.write_text("".join(json.dumps(row) + "\n" for row in rows))
                    case.save(state)
                    self.assert_refused(case, report, later=later)


if __name__ == "__main__":
    unittest.main()
