"""Typed worker statuses and the done-result final_report through both providers' real `record-wave`."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider

NODE = "U3[1]"
FINAL: dict[str, Any] = {
    "claims": [
        {"text": "unit tests pass", "label": "verified", "source": "python3 -m unittest: OK"},
        {"text": "no other caller reads it", "label": "inferred"},
    ],
    "did_not_verify": [{"item": "windows paths", "tag": "unverifiable", "reason": "no windows host"}],
}
STATUSES: dict[str, tuple[dict[str, Any], str, str]] = {
    "NEEDS_DECISION": (
        {"question": "Which?", "options": ["a", "b"], "recommended": "a"},
        "awaiting-input",
        "needs_human_input",
    ),
    "OUTSIDE_SCOPE": (
        {"requested_action": "edit docs", "scope_boundary": "src only"},
        "approval-gate",
        "needs_approval",
    ),
    "IRREVERSIBLE_ACTION": (
        {"action": "drop table", "why_irreversible": "no backup", "rollback": "none"},
        "approval-gate",
        "needs_approval",
    ),
}


def typed(status: str, **over: object) -> dict[str, Any]:
    """A valid typed worker status with overrides."""
    result: dict[str, Any] = {"status": status, "worker": "w1", "summary": "blocked", "confidence": "verified"}
    result.update(STATUSES[status][0])
    result.update(over)
    return result


class WorkerStatusRecordWaveTests(unittest.TestCase):
    """Both providers validate before the unchanged core and write the typed rows in the same locked save."""

    def setUp(self) -> None:
        """Isolated native fixtures for both providers."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp, self.made = Path(temporary.name), 0

    @property
    def providers(self) -> list[Provider]:
        """A fresh pair of isolated providers per access, so cases never share a transcript."""
        self.made += 1
        root = self.tmp / str(self.made)
        root.mkdir()
        return [Provider(root, name) for name in ("claude", "codex")]

    def record(self, provider: Provider, result: dict[str, Any], outcome: str = "done") -> CompletedProcess[str]:
        """Open a wave, launch its worker, and record `result` for the node."""
        provider.success("begin-wave")
        report = provider.launch(outcome)
        report["results"][NODE] = result
        return provider.call("record-wave", json.dumps(report))

    def test_malformed_status_rejects_the_whole_report_with_state_unchanged(self) -> None:
        """Missing option list, unknown field, one option: coded refusal, bytes unchanged, one refused trace row."""
        missing = typed("NEEDS_DECISION")
        del missing["options"]
        cases = {
            "worker_status_missing_field": missing,
            "worker_status_unknown_field": typed("OUTSIDE_SCOPE", extra=1),
            "worker_status_bad_field": typed("NEEDS_DECISION", options=["only"]),
            "worker_status_unknown_status": {"status": "DONE", "worker": "w"},
        }
        for code, result in cases.items():
            for provider in self.providers:
                with self.subTest(provider=provider.name, code=code):
                    provider.success("begin-wave")
                    report = provider.launch("failed")
                    report["results"][NODE] = result
                    before = provider.path.read_bytes()
                    done = provider.call("record-wave", json.dumps(report))
                    self.assertEqual(done.returncode, 1, done.stdout)
                    self.assertIn(f"[reason_code={code}]", done.stderr)
                    self.assertEqual(provider.path.read_bytes(), before)
                    trace = provider.path.with_name("recovery-trace.jsonl").read_text()
                    self.assertIn(f'"reason_code": "{code}"', trace)

    def test_each_valid_status_records_consumes_a_retry_and_writes_one_stop_row(self) -> None:
        """worker_statuses row, retry consumed, exactly one typed stop row bound to the new revision."""
        for status, (_, category, code) in STATUSES.items():
            for provider in self.providers:
                with self.subTest(provider=provider.name, status=status):
                    done = self.record(provider, typed(status), "failed")
                    self.assertEqual(done.returncode, 0, done.stderr)
                    state = provider.read()
                    node = state["graph"]["nodes"][NODE]
                    self.assertEqual((node["status"], node["retry"]["attempts"]), ("pending", 1))
                    self.assertEqual(
                        state["worker_statuses"],
                        [
                            {
                                "seq": 1,
                                "node": NODE,
                                "wave_id": "wave-2",
                                "status": status,
                                "payload": typed(status),
                                "decision_pending": True,
                                "revision": state["revision"],
                            }
                        ],
                    )
                    rows = state["stops"]
                    self.assertEqual(len(rows), 1)
                    self.assertEqual((rows[0]["category"], rows[0]["reason_code"]), (category, code))
                    self.assertEqual((rows[0]["revision"], rows[0]["consumed"]), (state["revision"], False))
                    self.assertIn(
                        f"worker_status_{status.lower()}", provider.path.with_name("recovery-trace.jsonl").read_text()
                    )

    def test_pending_decision_blocks_readiness_and_start_until_resolved(self) -> None:
        """A real typed result inhibits another wave until record-decision resolves it."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                result = self.record(provider, typed("NEEDS_DECISION"), "failed")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["ready"], [])
                self.assertEqual(provider.success("inspect")["ready"], [])
                before = provider.path.read_bytes()
                self.assertEqual(provider.call("begin-wave").returncode, 1)
                self.assertEqual(provider.path.read_bytes(), before)
                provider.success(
                    "record-decision",
                    "--session",
                    provider.session,
                    "--phase",
                    "implementation",
                    "--decision",
                    "answer",
                    "--chosen",
                    "a",
                    "--worker-status-seq",
                    "1",
                )
                self.assertEqual(provider.success("inspect")["ready"], [NODE])
                provider.success("begin-wave")

    def test_answer_at_retry_cap_keeps_terminal_evidence(self) -> None:
        """A human answer cannot reuse the fifth native evidence attempt."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                maximum = provider.read()["graph"]["nodes"][NODE]["retry"]["max"]
                for _ in range(maximum - 1):
                    failed = self.record(provider, {"outcome": "failed", "evidence": "prior failure"}, "failed")
                    self.assertEqual(failed.returncode, 0, failed.stderr)
                result = self.record(provider, typed("NEEDS_DECISION"), "failed")
                self.assertEqual(result.returncode, 0, result.stderr)
                blocked = provider.read()
                self.assertEqual(blocked["graph"]["hard_stop"]["reason"], "retry exhaustion")
                self.assertEqual(blocked["graph"]["nodes"][NODE]["retry"]["attempts"], maximum)
                self.assertEqual(provider.success("inspect")["ready"], [])
                provider.success(
                    "record-decision",
                    "--session",
                    provider.session,
                    "--phase",
                    "implementation",
                    "--decision",
                    "answer",
                    "--chosen",
                    "a",
                    "--worker-status-seq",
                    "1",
                )
                self.assertEqual(provider.success("inspect")["ready"], [])

    def test_terminal_decision_below_cap_uses_next_attempt(self) -> None:
        """An answered status extends the bound and retains its native attempt reference."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                state = provider.read()
                state["graph"]["nodes"][NODE]["retry"]["max"] = 2
                provider.write(state)
                failed = self.record(provider, {"outcome": "failed", "evidence": "prior failure"}, "failed")
                self.assertEqual(failed.returncode, 0, failed.stderr)
                result = self.record(provider, typed("NEEDS_DECISION"), "failed")
                self.assertEqual(result.returncode, 0, result.stderr)
                current = provider.read()
                node = current["graph"]["nodes"][NODE]
                self.assertEqual(node["retry"], {"attempts": 2, "max": 3})
                status_seq = str(current["worker_statuses"][-1]["seq"])
                provider.success(
                    "record-decision",
                    "--session",
                    provider.session,
                    "--phase",
                    "implementation",
                    "--decision",
                    "answer",
                    "--chosen",
                    "a",
                    "--worker-status-seq",
                    status_seq,
                )
                self.assertEqual(provider.success("inspect")["ready"], [NODE])
                failed = self.record(provider, {"outcome": "failed", "evidence": "next attempt"}, "failed")
                self.assertEqual(failed.returncode, 0, failed.stderr)
                self.assertEqual(provider.read()["graph"]["nodes"][NODE]["retry"]["attempts"], 3)

    def test_malformed_status_storage_inhibits_readiness(self) -> None:
        """Malformed rows fail closed instead of being mistaken for resolved decisions."""
        cases: list[Any] = [None, {}, [None], [{}], [{"node": NODE, "decision_pending": "false"}]]
        for rows in cases:
            for provider in self.providers:
                with self.subTest(provider=provider.name, rows=rows):
                    state = provider.read()
                    state["worker_statuses"] = rows
                    provider.write(state)
                    self.assertEqual(provider.success("inspect")["ready"], [])
                    before = provider.path.read_bytes()
                    self.assertEqual(provider.call("begin-wave").returncode, 1)
                    self.assertEqual(provider.path.read_bytes(), before)

    def test_pending_decision_does_not_block_an_unrelated_node(self) -> None:
        """Only the node awaiting an answer is removed from the next wave."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                state = provider.state((NODE, "U3[2]"))
                state["worker_statuses"] = [{"node": NODE, "decision_pending": True}]
                provider.write(state)
                self.assertEqual(provider.success("inspect")["ready"], ["U3[2]"])
                self.assertEqual(provider.success("begin-wave")["nodes"], ["U3[2]"])

    def test_pending_decision_blocks_stale_retry_without_mutation(self) -> None:
        """Both retry adapters refuse a stale node with an unanswered worker status."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                state = provider.read()
                state["graph"]["nodes"][NODE].update(
                    status="stale",
                    outcome="stale",
                    stale_check={"checked": True, "method": "inspection", "result": "absent"},
                )
                state["worker_statuses"] = [{"node": NODE, "decision_pending": True}]
                provider.write(state)
                before = provider.path.read_bytes()
                result = provider.call(
                    "respawn-stale", "--session", provider.session, "--node", NODE, "--reason", "retry"
                )
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("decision", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_pending_decision_blocks_live_authorization(self) -> None:
        """A pending status appearing during a wave cannot authorize its native dispatch."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                wave = provider.success("begin-wave")
                dispatch = wave["dispatches"][0]
                prompt = dispatch["prompt_prefix"] + "\n" + dispatch["prompt_sections"]
                state = provider.read()
                state["worker_statuses"] = [{"node": NODE, "decision_pending": True}]
                provider.write(state)
                before = provider.path.read_bytes()
                args: tuple[str, ...]
                if provider.name == "claude":
                    args = ("--prompt", prompt, "--subagent-type", "coderails:loop-worker")
                else:
                    message = provider.home / "message.txt"
                    message.write_text(prompt, encoding="utf-8")
                    args = (
                        "--dispatch-id",
                        dispatch["dispatch_id"],
                        "--message-file",
                        str(message),
                        "--agent-type",
                        "loop-worker",
                        "--task-name",
                        dispatch["task_name"],
                    )
                result = provider.call("authorize-dispatch", "--session", provider.session, *args)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("decision", result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)

    def test_codex_stop_guard_releases_the_status_row_once(self) -> None:
        """The recorded row releases the Codex Stop guard exactly once, with no text parsing."""
        provider = self.providers[1]
        self.assertEqual(self.record(provider, typed("NEEDS_DECISION"), "failed").returncode, 0)
        payload = {"session_id": provider.session, "cwd": str(provider.home), "last_assistant_message": "pausing"}
        self.assertEqual(provider.hook("graph_completion_guard", payload).stdout, "")
        self.assertEqual(json.loads(provider.hook("graph_completion_guard", payload).stdout)["decision"], "block")

    def test_done_without_a_valid_final_report_is_rejected_on_a_required_dispatch(self) -> None:
        """Absent or malformed final_report on a done result: whole report refused, bytes unchanged."""
        bad: dict[str, Any] = {
            "outcome": "done",
            "evidence": "ran",
            "final_report": {"claims": [], "did_not_verify": []},
        }
        absent: dict[str, Any] = {"outcome": "done", "evidence": "ran"}
        mislabeled = copy.deepcopy(FINAL)
        mislabeled["claims"][0]["label"] = "sure"
        wrong: dict[str, Any] = {"outcome": "done", "evidence": "ran", "final_report": mislabeled}
        for result in (absent, bad, wrong):
            for provider in self.providers:
                with self.subTest(provider=provider.name, result=sorted(result)):
                    provider.success("begin-wave")
                    report = provider.launch()
                    report["results"][NODE] = result
                    before = provider.path.read_bytes()
                    done = provider.call("record-wave", json.dumps(report))
                    self.assertEqual(done.returncode, 1, done.stdout)
                    self.assertIn("[reason_code=final_report_invalid]", done.stderr)
                    self.assertEqual(provider.path.read_bytes(), before)

    def test_valid_final_report_is_stored_and_stripped_before_the_core(self) -> None:
        """A done result with a valid report records normally and keeps the report under final_reports."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                done = self.record(provider, {"outcome": "done", "evidence": "ran", "final_report": FINAL})
                self.assertEqual(done.returncode, 0, done.stderr)
                state = provider.read()
                self.assertEqual(state["final_reports"], {NODE: FINAL})
                self.assertEqual(state["graph"]["nodes"][NODE]["status"], "done")
                self.assertNotIn("worker_statuses", state)
                self.assertNotIn("stops", state)

    def test_failed_result_needs_no_final_report(self) -> None:
        """Only `done` requires the report; a plain failed result records exactly as before."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                done = self.record(provider, {"outcome": "failed", "evidence": "gave up"}, "failed")
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertNotIn("final_reports", provider.read())

    def test_pre_conversion_state_without_dispatch_records_is_unaffected(self) -> None:
        """No dispatch record for the node: an untyped done result records with no final_report, as before."""
        for provider in self.providers:
            with self.subTest(provider=provider.name):
                provider.success("begin-wave")
                report = provider.launch()
                state = provider.read()
                state["state_minor"] = 1
                state["graph"]["dispatches"] = {}
                state["graph"]["contract_from_revision"] = 99
                provider.write(state)
                done = provider.call("record-wave", json.dumps(report))
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(provider.read()["graph"]["nodes"][NODE]["status"], "done")


if __name__ == "__main__":
    unittest.main()
