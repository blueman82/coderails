"""Current Note joins must preserve selected evidence and conditional metadata."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from typing import Any

from hooks.scripts.tests.lib import claude_transcript_fixture as graph_fixture
from scripts.lib import decision_record as dr
from scripts.lib import handoff_derive
from scripts.lib import memory_adapter as ma
from scripts.lib import memory_request as mr
from scripts.tests import fake_muninn_current as fc
from scripts.tests.current_consumers_test import ROOT, CurrentFixture


class CurrentReader(CurrentFixture):
    """Change one identity or physical fact while all other public fields stay valid."""

    def read(self) -> Any:  # noqa: ANN401
        """Exercise the maintained request reader with the retained submission binding."""
        return mr.inspect(
            fc.RID,
            "L1",
            "decision",
            fc.CLAIM,
            expected_window=self.data["request"]["window"],
            expected_project=str(self.project),
        )

    def test_all_supports_and_actual_quote_reach_reader(self) -> None:
        """First-ref projection and manufactured empty quotes are not citations."""
        result = self.read()
        self.assertNotIsInstance(result, ma.Degraded, result)
        self.assertEqual(result.quote, fc.QUOTE)
        self.assertEqual(result.revision, 3)
        self.assertEqual(len(result.supports), 2)
        self.assertEqual(result.metadata()["privacy_classification"], "unknown")

    def test_second_changed_physical_support_refuses_current_record(self) -> None:
        """Checking just the display citation misses a changed secondary source."""
        original = self.root / "original.jsonl"
        lines = original.read_text().splitlines()
        lines[1] = lines[1].replace("unchanged", "changed")
        original.write_text("\n".join(lines) + "\n")
        result = self.read()
        self.assertIsInstance(result, ma.Degraded, result)
        self.assertEqual(result.reason, "learning_source_changed")

    def test_conditions_reason_expiry_and_supports_survive(self) -> None:
        """Projection must not silently remove an owner condition or expiry condition."""
        self.data["notes"][0]["body"]["conditions"] = ["Only after owner approval."]
        self.data["notes"][0]["expiry"] = {
            "at": 4102444800.0,
            "condition": "Until the release ends.",
            "evidence_refs": [fc.EID],
        }
        self.save()
        result = self.read()
        self.assertNotIsInstance(result, ma.Degraded, result)
        metadata = result.metadata()
        self.assertEqual(metadata["body"]["conditions"], ["Only after owner approval."])
        self.assertEqual(metadata["body"]["reason"], "The owner chose the queue.")
        self.assertEqual(metadata["expiry"]["condition"], "Until the release ends.")
        self.assertEqual(metadata["expiry"]["at"], 4102444800.0)
        self.assertFalse(metadata["use_allowed"])
        self.assertEqual(metadata["use_reason"], "learning_conditional_use_unsupported")

    def test_identity_and_currentness_adverse_inputs_never_become_written(self) -> None:
        """Receipt, exact task/project, revision, expiry and form are separate joins."""
        baseline = copy.deepcopy(self.data)
        cases = ("foreign_receipt", "foreign_project", "foreign_task", "stale", "expired", "guide", "ambiguous")
        for case in cases:
            self.data = copy.deepcopy(baseline)
            note = self.data["notes"][0]
            if case == "foreign_receipt":
                self.data["receipt"]["request_id"] = "R_" + "9" * 32
            elif case == "foreign_project":
                note["body"]["scope"]["project_id"] = "/another/project"
            elif case == "foreign_task":
                note["body"]["scope"]["task"] = "another-task"
            elif case == "stale":
                note["revision"] = 4
            elif case == "expired":
                note["expiry"] = {"at": 1.0, "condition": None, "evidence_refs": [fc.EID]}
            elif case == "guide":
                note["body"] = {
                    "form": "guide",
                    "kind": "decision",
                    "scope": note["body"]["scope"],
                    "title": "Guide",
                    "summary": {"text": "Summary", "evidence_refs": [fc.EID]},
                    "applicability": [],
                    "steps": [{"key": "one", "claim": {"text": "Step", "evidence_refs": [fc.EID]}, "depends_on": []}],
                    "decision_points": [],
                    "pitfalls": [],
                    "reason": "Guide",
                }
            else:
                duplicate = copy.deepcopy(note)
                duplicate["id"] = "K_" + "8" * 32
                self.data["notes"].append(duplicate)
                self.data["receipt"]["applied"].append({"knowledge_id": duplicate["id"], "revision": 3})
            self.save()
            with self.subTest(case=case):
                result = self.read()
                self.assertIsInstance(result, ma.Degraded)
                if case == "guide":
                    self.assertEqual(result.reason, "learning_form_unsupported")

    def test_missing_selected_evidence_wrong_role_and_scope_are_explicit(self) -> None:
        """Retained refs alone, nonowner content, or foreign evidence cannot supply a user citation."""
        baseline = copy.deepcopy(self.data)
        for case in ("missing_selection", "wrong_role", "wrong_scope", "blank_quote", "wrong_ref"):
            self.data = copy.deepcopy(baseline)
            if case == "missing_selection":
                self.data["evidence"] = []
            elif case == "wrong_role":
                self.data["evidence"][0]["authority"] = "reported"
                self.data["evidence"][0]["evidence_type"] = "assistant_report"
            elif case == "wrong_scope":
                self.data["evidence"][1]["scope"]["project_id"] = "/another/project"
            elif case == "blank_quote":
                self.data["evidence"][0]["excerpt"] = ""
            else:
                self.data["notes"][0]["evidence_sources"][1]["ref"] = "codex:other:2.1"
            self.save()
            with self.subTest(case=case):
                result = self.read()
                self.assertIsInstance(result, ma.Degraded, result)

    def test_no_change_and_accepted_only_remain_explicit(self) -> None:
        """Acceptance and a no-change receipt cannot masquerade as a saved Note."""
        self.data["receipt"].update(applied=[], outcome="no_change", no_change_reason="Nothing to add.")
        self.save()
        result = self.read()
        self.assertIsInstance(result, ma.Degraded, result)
        self.assertEqual(result.reason, "learning_no_change")
        self.data["receipt"] = None
        self.save()
        result = self.read()
        self.assertIsInstance(result, (mr.Pending, ma.Degraded), result)

    def test_extra_discovery_filters_metadata_before_reading_foreign_requests(self) -> None:
        """A foreign request must never have its evidence detail opened by handoff."""
        extra_id = "R_" + "9" * 32
        detail = {
            key: copy.deepcopy(self.data[key])
            for key in ("request", "receipt", "attempts", "calls", "evidence", "correction_status", "diagnostics")
        }
        detail["request"]["id"] = extra_id
        detail["receipt"]["request_id"] = extra_id
        foreign = copy.deepcopy(detail["request"])
        foreign["id"] = "R_" + "8" * 32
        foreign["scope"]["project_id"] = "/foreign/project"
        wrong_task = copy.deepcopy(detail["request"])
        wrong_task["id"] = "R_" + "7" * 32
        wrong_task["scope"]["task"] = "other-task"
        self.data["requests"] = [foreign, wrong_task, detail["request"]]
        self.data["extra_details"] = {extra_id: detail}
        self.save()
        result = mr.task_notes("L1", "decision")
        self.assertNotIsInstance(result, ma.Degraded, result)
        assert isinstance(result, list)
        self.assertEqual([(note.id, note.request_id) for note in result], [(fc.KID, extra_id)])
        calls = [json.loads(line)["args"] for line in (self.root / "calls.jsonl").read_text().splitlines()]
        shown = [args[2] for args in calls if args[:2] == ["learn", "show"]]
        self.assertEqual(shown, [extra_id])
        self.assertFalse(any("--all-projects" in args for args in calls))

    def test_extra_discovery_refuses_ambiguous_receipts_and_scan_limit(self) -> None:
        """Neither a second matching receipt nor a truncated scan can select an identity."""
        extra_id = "R_" + "9" * 32
        detail = {
            key: copy.deepcopy(self.data[key])
            for key in ("request", "receipt", "attempts", "calls", "evidence", "correction_status", "diagnostics")
        }
        detail["request"]["id"] = extra_id
        detail["receipt"]["request_id"] = extra_id
        self.data["requests"] = [self.data["request"], detail["request"]]
        self.data["extra_details"] = {extra_id: detail}
        self.save()
        self.assertEqual(mr.task_notes("L1", "decision"), ma.Degraded("learning_record_ambiguous"))
        self.data["requests"] = [self.data["request"]] * 101
        self.save()
        self.assertEqual(mr.task_notes("L1", "decision"), ma.Degraded("learning_read_limit"))

    def test_shortened_request_receipt_and_view_are_not_supported_models(self) -> None:
        """A partial fixture must not silently define a looser contract than the public models."""
        baseline = copy.deepcopy(self.data)
        for object_name, field in (("request", "policy_digest"), ("receipt", "attempt_id"), ("note", "origin")):
            self.data = copy.deepcopy(baseline)
            target = self.data["notes"][0] if object_name == "note" else self.data[object_name]
            target.pop(field)
            self.save()
            with self.subTest(object=object_name):
                self.assertIsInstance(self.read(), ma.Degraded)

    def test_retained_window_and_each_pending_state_remain_exact(self) -> None:
        """A foreign window cannot replace the submitted binding, including before completion."""
        retained = copy.deepcopy(self.data["request"]["window"])
        for state in ("pending", "running", "waiting"):
            self.data["request"]["state"] = state
            self.data["receipt"] = None
            self.save()
            observed = self.read()
            self.assertIsInstance(observed, mr.Pending)
            assert isinstance(observed, mr.Pending)
            self.assertEqual(
                (observed.request_id, observed.window, observed.project_id), (fc.RID, retained, str(self.project))
            )
        self.data["request"]["window"]["through_line"] = 99
        self.save()
        result = mr.inspect(
            fc.RID, "L1", "decision", fc.CLAIM, expected_window=retained, expected_project=str(self.project)
        )
        self.assertEqual(result, ma.Degraded("learning_request_mismatch"))

    def test_handoff_preserves_supported_extra_when_another_form_is_unsupported(self) -> None:
        """One unsupported external Guide must not discard another verified extra decision."""
        extra = copy.deepcopy(self.data["notes"][0])
        extra["id"] = "K_" + "6" * 32
        extra["body"]["content"] = "Keep this supported external decision."
        guide = copy.deepcopy(extra)
        guide["id"] = "K_" + "7" * 32
        guide["body"] = {
            "form": "guide",
            "kind": "decision",
            "scope": extra["body"]["scope"],
            "title": "Unsupported Guide",
            "summary": {"text": "Summary", "evidence_refs": [fc.EID]},
            "applicability": [],
            "steps": [{"key": "one", "claim": {"text": "Step", "evidence_refs": [fc.EID]}, "depends_on": []}],
            "decision_points": [],
            "pitfalls": [],
            "reason": "An explicit form boundary.",
        }
        self.data["notes"].extend([extra, guide])
        self.data["receipt"]["applied"].extend([{"knowledge_id": note["id"], "revision": 3} for note in (extra, guide)])
        self.save()
        state = dr.add_decision(
            {"session_id": "s1", "loop_id": "L1", "revision": 1}, "s1", "2.5", "choose the bronze queue", "L1", 1
        )["state"]
        state["decisions_absorbed"][0]["muninn"] = {
            "state": "written",
            "id": fc.KID,
            "request_id": fc.RID,
            "request_window": self.data["request"]["window"],
            "project_id": str(self.project),
            "reason_code": "ok",
        }
        degraded: list[dict[str, str]] = []
        result = handoff_derive.decisions(state, "L1", "s1", degraded)
        self.assertEqual({row["id"] for row in result}, {fc.KID, extra["id"]})
        self.assertIn({"source": "decisions", "reason": "learning_form_unsupported"}, degraded)


class HandoffBinding(CurrentFixture):
    """Local request assertions cannot gain a second, weaker route into handoff."""

    def test_rejected_local_binding_keeps_only_independently_supported_extras(self) -> None:
        """Actual provider flush and handoff preserve rejection without hiding valid task decisions."""
        text = "Use the bronze queue for this routing decision."
        claim = "routing: " + text
        for provider in (ROOT, ROOT / "packages/codex"):
            for case in ("changed_window", "multiple_notes", "unknown_binding"):
                with self.subTest(provider=provider, case=case):
                    self.data = fc.fixture(self.root, self.project, claim=claim)
                    retained = copy.deepcopy(self.data["request"]["window"])
                    extra = copy.deepcopy(self.data["notes"][0])
                    extra["id"] = "K_" + "a" * 32
                    extra["body"]["content"] = "Preserve the other decision from this receipt."
                    self.data["notes"].append(extra)
                    self.data["receipt"]["applied"].append({"knowledge_id": extra["id"], "revision": 3})
                    if case == "changed_window":
                        retained["boundary_hash"] = "b" * 64
                    elif case == "multiple_notes":
                        duplicate = copy.deepcopy(self.data["notes"][0])
                        duplicate["id"] = "K_" + "c" * 32
                        self.data["notes"].append(duplicate)
                        self.data["receipt"]["applied"].append({"knowledge_id": duplicate["id"], "revision": 3})
                    standalone = copy.deepcopy(self.data["notes"][0])
                    standalone["id"] = "K_" + "d" * 32
                    detail = {
                        key: copy.deepcopy(self.data[key])
                        for key in (
                            "request",
                            "receipt",
                            "attempts",
                            "calls",
                            "evidence",
                            "correction_status",
                            "diagnostics",
                        )
                    }
                    detail["request"]["id"] = "R_" + "e" * 32
                    detail["receipt"].update(
                        request_id=detail["request"]["id"],
                        applied=[{"knowledge_id": standalone["id"], "revision": 3}],
                    )
                    self.data["notes"].append(standalone)
                    self.data["requests"] = [self.data["request"], detail["request"]]
                    self.data["extra_details"] = {detail["request"]["id"]: detail}
                    self.save()
                    state: dict[str, Any] = {**graph_fixture.state(), "session_id": "s1", "loop_id": "L1"}
                    state = dr.add_decision(state, "s1", "routing", text, "L1", state["revision"])["state"]
                    field = {
                        "state": "unknown" if case == "unknown_binding" else "pending",
                        "id": None,
                        "request_id": fc.RID,
                        "request_window": retained,
                        "project_id": str(self.project),
                        "reason_code": "learning_request_unknown",
                    }
                    if case == "unknown_binding":
                        field.pop("request_window")
                    state["decisions_absorbed"][0]["muninn"] = field
                    path = self.root / f"{provider.name}-{case}" / "s1/progress.json"
                    path.parent.mkdir(parents=True)
                    path.write_text(json.dumps(state))
                    flushed = subprocess.run(
                        [
                            sys.executable,
                            str(provider / "skills/agentic-loop/scripts/graph.py"),
                            "flush-decisions",
                            str(path),
                            "--session",
                            "s1",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    self.assertEqual(flushed.returncode, 3, flushed.stdout + flushed.stderr)
                    before = path.read_bytes(), (self.root / "data.json").read_bytes()
                    run = subprocess.run(
                        [sys.executable, str(provider / "scripts/lib/handoff_derive.py"), str(path), "--session", "s1"],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    payload = json.loads(run.stdout)
                    self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
                    rows = payload["decisions"]
                    local = [row for row in rows if row["source"] == "progress"]
                    self.assertEqual(len(local), 1)
                    self.assertIsNone(local[0]["cite"])
                    self.assertIsNone(local[0]["quote"])
                    self.assertIn({"source": "decisions", "reason": local[0]["reason_code"]}, payload["degraded"])
                    self.assertEqual(
                        {row["id"] for row in rows if row["source"] == "muninn"}, {extra["id"], standalone["id"]}
                    )
                    self.assertTrue(all(row["quote"] for row in rows if row["source"] == "muninn"))
                    self.assertEqual((path.read_bytes(), (self.root / "data.json").read_bytes()), before)
        calls = [json.loads(line)["args"] for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertFalse(any(args[:2] == ["learn", "request"] for args in calls))


if __name__ == "__main__":
    unittest.main()
