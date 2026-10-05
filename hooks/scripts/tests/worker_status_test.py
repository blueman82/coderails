#!/usr/bin/env python3
"""Pin worker statuses: valid/invalid per status, unknown refused, decision request, graph_semantics untouched."""

from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills/agentic-loop/scripts"))
import worker_status as ws  # noqa: E402

EXTRAS: dict[str, dict[str, Any]] = {
    "NEEDS_DECISION": {"question": "Which?", "options": ["a", "b"], "recommended": "a"},
    "OUTSIDE_SCOPE": {"requested_action": "edit docs", "scope_boundary": "src only"},
    "IRREVERSIBLE_ACTION": {"action": "drop table", "why_irreversible": "no backup", "rollback": "none"},
}


def base(status: str, **over: object) -> dict[str, Any]:
    """A valid result for a status, with overrides."""
    obj: dict[str, Any] = {"status": status, "worker": "w1", "summary": "blocked", "confidence": "verified"}
    obj.update(EXTRAS[status])
    obj.update(over)
    return obj


class ValidateTests(unittest.TestCase):
    """Every status has a valid shape and refusals carry stable codes."""

    def test_valid_each_status(self) -> None:
        """All three statuses validate; recommended may be None."""
        for status in ws.STATUSES:
            self.assertEqual(ws.validate(base(status)), "ok", status)
        self.assertEqual(ws.validate(base("NEEDS_DECISION", recommended=None)), "ok")

    def test_refusal_table(self) -> None:
        """Unknown status, missing/unknown/bad fields, and non-objects."""
        missing = base("OUTSIDE_SCOPE")
        del missing["scope_boundary"]
        cases: list[tuple[object, str]] = [
            ("x", "not_an_object"),
            ({"status": "DONE"}, "unknown_status"),
            ({}, "unknown_status"),
            (missing, "missing_field"),
            (base("OUTSIDE_SCOPE", extra=1), "unknown_field"),
            (base("OUTSIDE_SCOPE", summary=" "), "bad_field"),
            (base("OUTSIDE_SCOPE", confidence="sure"), "bad_field"),
            (base("NEEDS_DECISION", options=["a"]), "bad_field"),
            (base("NEEDS_DECISION", recommended="z"), "bad_field"),
            (base("IRREVERSIBLE_ACTION", rollback=""), "bad_field"),
        ]
        for obj, code in cases:
            self.assertEqual(ws.validate(obj), code, obj)

    def test_decision_request(self) -> None:
        """Valid results become a request; invalid ones raise with the reason code."""
        request = ws.to_decision_request(base("NEEDS_DECISION"))
        self.assertEqual((request["ask"], request["options"], request["recommended"]), ("Which?", ["a", "b"], "a"))
        self.assertIn("src only", ws.to_decision_request(base("OUTSIDE_SCOPE"))["ask"])
        self.assertIn("drop table", ws.to_decision_request(base("IRREVERSIBLE_ACTION"))["ask"])
        with self.assertRaises(ValueError) as caught:
            ws.to_decision_request({"status": "NOPE"})
        self.assertEqual(str(caught.exception), "unknown_status")

    def test_graph_semantics_untouched_and_codex_copy_in_sync(self) -> None:
        """Negative control: graph_semantics is unchanged vs origin/main, and the Codex copy is byte-identical."""
        for path in (
            "skills/agentic-loop/scripts/graph_semantics.py",
            "packages/codex/skills/agentic-loop/scripts/graph_semantics.py",
            "packages/graph-semantics/graph_semantics.py",
        ):
            source = (ROOT / path).read_text()
            self.assertNotIn("worker_status", source, path)
            self.assertNotIn("NEEDS_DECISION", source, path)
        digest = [hashlib.sha256((ROOT / p / "worker_status.py").read_bytes()).hexdigest() for p in
                  ("skills/agentic-loop/scripts", "packages/codex/skills/agentic-loop/scripts")]  # fmt: skip
        self.assertEqual(digest[0], digest[1])


REPORT: dict[str, Any] = {
    "claims": [{"text": "tests pass", "label": "verified", "source": "unittest: OK"}, {"text": "x", "label": "guess"}],
    "did_not_verify": [{"item": "windows", "tag": "unverifiable", "reason": "no host"}],
}


def state_with_record(required: bool = True) -> dict[str, Any]:
    """A minimal state: node U3[1] in active wave-2 with (or without) its dispatch record."""
    records = {"d1": {"node_id": "U3[1]", "wave_id": "wave-2", "final_report_required": required}}
    return {"graph": {"active_wave": {"wave_id": "wave-2", "nodes": ["U3[1]"]}, "dispatches": records}}


class FinalReportAndPrepareTests(unittest.TestCase):
    """classify_result, validate_final_report and the record-wave pre-processor."""

    def test_classify_result(self) -> None:
        """Only a result carrying a status key is typed."""
        self.assertEqual(ws.classify_result(base("OUTSIDE_SCOPE")), "typed")
        self.assertEqual(ws.classify_result({"status": "junk"}), "typed")
        self.assertEqual(ws.classify_result({"outcome": "done", "evidence": "x"}), "untyped")
        self.assertEqual(ws.classify_result("x"), "untyped")

    def test_final_report_table(self) -> None:
        """A valid report passes; every structural defect has a stable code."""
        self.assertEqual(ws.validate_final_report(REPORT), "ok")
        self.assertEqual(ws.validate_final_report({**REPORT, "did_not_verify": []}), "ok")
        no_source = {"claims": [{"text": "t", "label": "verified"}], "did_not_verify": []}
        cases: list[tuple[object, str]] = [
            ([], "not_an_object"),
            ({"claims": REPORT["claims"]}, "missing_field"),
            ({**REPORT, "extra": 1}, "unknown_field"),
            ({**REPORT, "claims": []}, "bad_field"),
            (no_source, "bad_field"),
            ({**REPORT, "claims": [{"text": "t", "label": "sure"}]}, "bad_field"),
            ({**REPORT, "claims": [{"text": " ", "label": "guess"}]}, "bad_field"),
            ({**REPORT, "claims": [{"text": "t", "label": "guess", "other": 1}]}, "bad_field"),
            ({**REPORT, "did_not_verify": [{"item": "i", "tag": "later", "reason": "r"}]}, "bad_field"),
            ({**REPORT, "did_not_verify": [{"item": "i", "tag": "resolved"}]}, "bad_field"),
            ({**REPORT, "did_not_verify": "none"}, "bad_field"),
        ]
        for obj, code in cases:
            self.assertEqual(ws.validate_final_report(obj), code, obj)

    def test_prepare_translates_a_valid_status_and_refuses_a_bad_one(self) -> None:
        """Typed status becomes core `failed`; a malformed one raises with the worker_status_ code and the node."""
        core, statuses, reports = ws.prepare(state_with_record(), {"U3[1]": base("NEEDS_DECISION")})
        self.assertEqual(core["U3[1]"], {"outcome": "failed", "evidence": "NEEDS_DECISION: blocked"})
        self.assertEqual((statuses[0]["node"], statuses[0]["status"], reports), ("U3[1]", "NEEDS_DECISION", {}))
        with self.assertRaises(ws.WorkerResultError) as caught:
            ws.prepare(state_with_record(), {"U3[1]": base("NEEDS_DECISION", options=["a"])})
        self.assertEqual((caught.exception.code, caught.exception.node), ("worker_status_bad_field", "U3[1]"))

    def test_prepare_final_report_rules(self) -> None:
        """Required on done with a record; stripped when present; optional elsewhere; no record passes through."""
        done = {"outcome": "done", "evidence": "x"}
        with self.assertRaises(ws.WorkerResultError) as caught:
            ws.prepare(state_with_record(), {"U3[1]": done})
        self.assertEqual(caught.exception.code, "final_report_invalid")
        core, _, reports = ws.prepare(state_with_record(), {"U3[1]": {**done, "final_report": REPORT}})
        self.assertEqual((core["U3[1]"], reports), (done, {"U3[1]": REPORT}))
        bad: dict[str, Any] = {**done, "final_report": {"claims": []}}
        with self.assertRaises(ws.WorkerResultError):
            ws.prepare(state_with_record(), {"U3[1]": bad})
        failed = {"outcome": "failed", "evidence": "x"}
        self.assertEqual(ws.prepare(state_with_record(), {"U3[1]": failed})[0], {"U3[1]": failed})
        self.assertEqual(ws.prepare(state_with_record(False), {"U3[1]": done})[0], {"U3[1]": done})
        self.assertEqual(ws.prepare({"graph": {"active_wave": None}}, {"U3[1]": done})[0], {"U3[1]": done})

    def test_record_into_and_stop_precedence(self) -> None:
        """Rows are sequenced and bound to the post-record revision; approval-gate outranks awaiting-input."""
        proposed: dict[str, Any] = {"revision": 3}
        statuses = [
            {"node": "U3[1]", "status": "NEEDS_DECISION", "payload": base("NEEDS_DECISION")},
            {"node": "U3[2]", "status": "OUTSIDE_SCOPE", "payload": base("OUTSIDE_SCOPE")},
        ]
        ws.record_into(proposed, "wave-2", statuses, {"U3[1]": REPORT})
        ws.record_into(proposed, "wave-4", statuses[:1], {})
        self.assertEqual([r["seq"] for r in proposed["worker_statuses"]], [1, 2, 3])
        self.assertEqual({r["revision"] for r in proposed["worker_statuses"]}, {3})
        self.assertTrue(all(r["decision_pending"] for r in proposed["worker_statuses"]))
        self.assertEqual(ws.stop_for(statuses)[:2], ("approval-gate", "needs_approval"))
        self.assertEqual(ws.stop_for(statuses[:1])[:2], ("awaiting-input", "needs_human_input"))

    def test_append_decision_row_and_refusals(self) -> None:
        """The pure ledger core: typed row, resolved status, no input mutation, and each refusal code."""
        state: dict[str, Any] = {
            "session_id": "s",
            "revision": 4,
            "worker_statuses": [{"seq": 1, "decision_pending": True}],
        }
        fields: dict[str, str | None] = {"phase": " 2.6 ", "decision": "d", "chosen": "c", "flip_condition": None}
        proposed, row = ws.append_decision(state, "s", fields, 1)
        self.assertEqual(
            list(row), ["seq", "phase", "decision", "chosen", "worker_status_seq", "revision", "recorded_at"]
        )
        self.assertEqual((row["seq"], row["phase"], row["revision"]), (1, "2.6", 4))
        self.assertEqual(
            proposed["worker_statuses"][0], {"seq": 1, "decision_pending": False, "resolved_by_decision": 1}
        )
        self.assertNotIn("decisions_absorbed", state)
        bad: list[tuple[dict[str, Any], str, dict[str, str | None], int | None]] = [
            (state, "other", fields, None),
            (state, "s", {**fields, "chosen": " "}, None),
            ({**state, "decisions_absorbed": "torn"}, "s", fields, None),
            (state, "s", fields, 7),
            (proposed, "s", fields, 1),
        ]
        codes = ["foreign", "field", "state", "status", "status"]
        for (current, session, given, seq), code in zip(bad, codes):
            with self.assertRaises(ws.WorkerResultError) as caught:
                ws.append_decision(current, session, given, seq)
            self.assertEqual(caught.exception.code, f"record_decision_refused_{code}")

    def test_append_decision_binds_answer_to_the_status(self) -> None:
        """The answer must be a NEEDS_DECISION option; approval-gate statuses need the human-answer marker."""
        pending = {"decision_pending": True}
        state: dict[str, Any] = {
            "session_id": "s",
            "revision": 1,
            "worker_statuses": [
                {"seq": 1, "status": "NEEDS_DECISION", "payload": {"options": ["a", "b"]}, **pending},
                {"seq": 2, "status": "IRREVERSIBLE_ACTION", "payload": {}, **pending},
            ],
        }
        fields: dict[str, str | None] = {"phase": "p", "decision": "d", "chosen": "z"}
        for seq, human, code in ((1, False, "chosen"), (2, False, "human")):
            with self.assertRaises(ws.WorkerResultError) as caught:
                ws.append_decision(state, "s", fields, seq, human)
            self.assertEqual(caught.exception.code, f"record_decision_refused_{code}")
        ws.append_decision(state, "s", {**fields, "chosen": "b"}, 1)
        ws.append_decision(state, "s", fields, 2, True)

    def test_both_record_wave_paths_call_prepare(self) -> None:
        """Negative control anchor: deleting the pre-processor call from a provider fails here and in the CLI tests."""
        for path in (
            "hooks/scripts/lib/graph_dispatch.py",
            "packages/codex/skills/agentic-loop/scripts/graph_dispatch.py",
        ):
            self.assertIn("worker_status.prepare(", (ROOT / path).read_text(), path)


if __name__ == "__main__":
    unittest.main()
