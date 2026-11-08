"""Submission fences and revised extra decisions through actual provider consumers."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from hooks.scripts.tests.lib import claude_transcript_fixture as graph_fixture
from scripts.lib import decision_record as dr
from scripts.lib import memory_adapter as ma
from scripts.lib import memory_current as current
from scripts.lib import memory_request as mr
from scripts.lib import orders_ledger as ol
from scripts.lib import orders_request
from scripts.tests import fake_muninn_current as fc
from scripts.tests.current_consumers_test import ROOT, CurrentFixture
from scripts.tests.orders_lifecycle_test import progress


class RecoveryFixture(CurrentFixture):
    """Keep every CLI invocation inside the private public-shaped synthetic transport."""

    def cli(self, provider: Path, script: str, args: list[str]) -> tuple[int, dict[str, Any]]:
        """Read the actual consumer's exit status and JSON without replacing its outcome."""
        run = subprocess.run(
            [sys.executable, str(provider / script), *args], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(run.stderr, "", run.stderr)
        return run.returncode, json.loads(run.stdout)

    def submissions(self) -> int:
        """Count irreversible calls, excluding public help probes."""
        path = self.root / "calls.jsonl"
        rows = [json.loads(line)["args"] for line in path.read_text().splitlines()] if path.exists() else []
        return sum(args[:2] == ["learn", "request"] and "--help" not in args for args in rows)

    def decision(self, provider: Path, directory: Path) -> tuple[Path, dict[str, Any]]:
        """Author one graph decision through the actual provider command."""
        state = {**graph_fixture.state(), "session_id": "s1", "loop_id": "L1"}
        path = directory / "s1/progress.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(state))
        code, payload = self.cli(
            provider,
            "skills/agentic-loop/scripts/graph.py",
            [
                "record-decision",
                str(path),
                "--session",
                "s1",
                "--loop-id",
                "L1",
                "--revision",
                str(state["revision"]),
                "--phase",
                "routing",
                "--decision",
                "Use the bronze queue.",
            ],
        )
        self.assertEqual(code, 3, payload)
        return path, payload["muninn"]


class SubmissionFence(RecoveryFixture):
    """After a possible acceptance, local validation cannot authorize a second submission."""

    def test_project_failure_precedes_any_submission(self) -> None:
        """The mapped project must exist before a request can cross the transport boundary."""
        with mock.patch.object(current, "project", return_value=ma.Degraded("learning_project_unavailable")):
            result = mr.submit("s1", "L1")
        self.assertEqual(result, ma.Degraded("learning_project_unavailable"))
        self.assertEqual(self.submissions(), 0)

    def test_post_submission_unknown_retains_the_validation_cause(self) -> None:
        """An uncertain reply is fenced without presenting foreign response metadata as a save."""
        foreign = copy.deepcopy(self.data["request"])
        foreign["scope"]["project_id"] = "/synthetic/foreign-project"
        for reply, cause in (
            (ma.Degraded("muninn_timeout"), "muninn_timeout"),
            ("not-json", "muninn_bad_output"),
            (json.dumps(foreign), "learning_request_mismatch"),
        ):
            with (
                self.subTest(cause=cause),
                mock.patch.object(mr, "probe", return_value=None),
                mock.patch.object(ma, "run_cli", return_value=reply),
            ):
                result = mr.submit("s1", "L1")
                self.assertIsInstance(result, ma.Degraded)
                assert isinstance(result, ma.Degraded)
                self.assertEqual((result.reason, result.detail), ("learning_request_unknown", cause))

    def test_invalid_initial_reply_fences_order_and_decision_restarts(self) -> None:
        """Foreign scope, malformed window, and absent/invalid IDs cannot reopen a send."""
        for provider in (ROOT, ROOT / "packages/codex"):
            for case in ("foreign_scope", "invalid_window", "invalid_id", "no_view"):
                for consumer in ("decision", "order"):
                    with self.subTest(provider=provider, case=case, consumer=consumer):
                        self.data = fc.fixture(self.root, self.project)
                        if case == "foreign_scope":
                            self.data["request"]["scope"]["project_id"] = "/synthetic/other-project"
                        elif case == "invalid_window":
                            self.data["request"]["window"]["from_line"] = -7
                        elif case == "invalid_id":
                            self.data["request"]["id"] = "not-a-request-id"
                        else:
                            self.data["request"] = None
                        self.save()
                        before = self.submissions()
                        directory = self.root / f"{provider.name}-{case}-{consumer}"
                        if consumer == "decision":
                            path, first = self.decision(provider, directory)
                            for _ in range(2):
                                code, payload = self.cli(
                                    provider,
                                    "skills/agentic-loop/scripts/graph.py",
                                    ["flush-decisions", str(path), "--session", "s1"],
                                )
                                self.assertEqual(code, 3, payload)
                        else:
                            directory.mkdir()
                            progress(directory, "s1", "L1", "in-progress")
                            args = [
                                "--dir",
                                str(directory),
                                "--session",
                                "s1",
                                "record",
                                "--id",
                                "routing",
                                "--failure-mode",
                                "routing",
                                "--lesson",
                                "Use the bronze queue.",
                                "--loop",
                                "L1",
                            ]
                            initial_code, initial = self.cli(provider, "scripts/lib/orders.py", args)
                            self.assertEqual(initial_code, 3, initial)
                            first = initial["muninn"]
                            for _ in range(2):
                                code, payload = self.cli(provider, "scripts/lib/orders.py", args)
                                self.assertEqual(code, 3, payload)
                        self.assertEqual(self.submissions() - before, 1)
                        self.assertEqual((first["state"], first["id"]), ("unknown", None), first)

    def test_validated_request_survives_inspection_mismatch_then_recovers(self) -> None:
        """An already retained R-id stays inspect-only through later receipt errors."""
        for provider in (ROOT, ROOT / "packages/codex"):
            self.data = fc.fixture(self.root, self.project, claim="routing: Use the bronze queue.")
            self.save()
            before = self.submissions()
            path, first = self.decision(provider, self.root / f"{provider.name}-known")
            self.assertEqual(first["request_id"], fc.RID)
            self.data["receipt"]["request_id"] = "R_" + "b" * 32
            self.save()
            args = ["flush-decisions", str(path), "--session", "s1"]
            _, mismatch = self.cli(provider, "skills/agentic-loop/scripts/graph.py", args)
            rejected = mismatch["synced"][0]["muninn"]
            self.assertEqual(rejected["reason_code"], "learning_request_mismatch")
            self.assertEqual(rejected["request_id"], fc.RID)
            self.assertIsNone(rejected["id"])
            self.data["receipt"]["request_id"] = fc.RID
            self.save()
            code, recovered = self.cli(provider, "skills/agentic-loop/scripts/graph.py", args)
            self.assertEqual(code, 0, recovered)
            self.assertEqual(recovered["synced"][0]["muninn"]["id"], fc.KID)
            self.assertEqual(self.submissions() - before, 1)

    def test_known_request_survives_project_lookup_error_in_each_consumer(self) -> None:
        """A later read error cannot discard a previously validated request/window/project."""
        directory = self.root / "read-only-order"
        directory.mkdir()
        field = {
            "state": "pending",
            "id": None,
            "request_id": fc.RID,
            "request_window": copy.deepcopy(self.data["request"]["window"]),
            "project_id": str(self.project),
        }
        row: dict[str, Any] = {"phase": "2.5", "decision": "choose the bronze queue", "muninn": field}
        with mock.patch.object(current, "project", return_value=ma.Degraded("learning_project_unavailable")):
            failed = mr.decision_field(row, "L1", "s1")
        self.assertEqual(failed["request_id"], fc.RID)
        row["muninn"] = failed
        self.assertEqual(mr.decision_field(row, "L1", "s1")["state"], "written")
        claim = "Use the bronze queue."
        self.data = fc.fixture(self.root, self.project, kind="lesson", claim=claim)
        self.save()
        order = {
            "id": "routing",
            "lesson": claim,
            "muninn": {
                **field,
                "source_session": "s1",
                "task": "L1",
                "claim_sha256": hashlib.sha256(claim.encode()).hexdigest(),
            },
        }
        with mock.patch.object(current, "project", return_value=ma.Degraded("learning_project_unavailable")):
            failed = orders_request.sync_order(order, "s1", directory, ol.empty(), "L1")
        self.assertEqual(failed["request_id"], fc.RID)
        order["muninn"] = failed
        self.assertFalse(orders_request.needs_submit(order, "L1", "s1"))
        recovered = orders_request.sync_order(order, "s1", directory, ol.empty(), "L1")
        self.assertEqual((recovered["state"], recovered["request_id"]), ("written", fc.RID))
        self.assertEqual(self.submissions(), 0)

    def test_order_retains_request_across_bad_receipt_and_recovers(self) -> None:
        """Each provider's record callback inspects the saved request through a receipt mismatch."""
        for provider in (ROOT, ROOT / "packages/codex"):
            self.data = fc.fixture(self.root, self.project, kind="lesson", claim="Use the bronze queue.")
            self.save()
            before = self.submissions()
            directory = self.root / f"{provider.name}-receipt-order"
            directory.mkdir()
            progress(directory, "s1", "L1", "in-progress")
            args = [
                "--dir",
                str(directory),
                "--session",
                "s1",
                "record",
                "--id",
                "routing",
                "--failure-mode",
                "routing",
                "--lesson",
                "Use the bronze queue.",
                "--loop",
                "L1",
            ]
            _, first = self.cli(provider, "scripts/lib/orders.py", args)
            self.assertEqual(first["muninn"]["request_id"], fc.RID)
            self.data["receipt"]["request_id"] = "R_" + "b" * 32
            self.save()
            code, refused = self.cli(provider, "scripts/lib/orders.py", args)
            self.assertEqual(code, 3, refused)
            self.assertEqual(refused["muninn"]["request_id"], fc.RID)
            self.assertEqual(refused["muninn"]["reason_code"], "learning_request_mismatch")
            self.data["receipt"]["request_id"] = fc.RID
            self.save()
            code, recovered = self.cli(provider, "scripts/lib/orders.py", args)
            self.assertEqual(code, 0, recovered)
            self.assertEqual(recovered["muninn"]["id"], fc.KID)
            self.assertEqual(self.submissions() - before, 1)


class RevisedExtra(RecoveryFixture):
    """Only a current successful local citation can hide an extra K-id."""

    def test_stale_local_k_does_not_hide_revised_assertion(self) -> None:
        """An independent receipt or a different assertion on the same receipt remains visible."""
        for provider in (ROOT, ROOT / "packages/codex"):
            for owner in ("independent", "same_request"):
                with self.subTest(provider=provider, owner=owner):
                    self.data = fc.fixture(self.root, self.project, claim="routing: Use the bronze queue.")
                    state: dict[str, Any] = {**graph_fixture.state(), "session_id": "s1", "loop_id": "L1"}
                    state = dr.add_decision(state, "s1", "routing", "Use the bronze queue.", "L1", state["revision"])[
                        "state"
                    ]
                    state["decisions_absorbed"][0]["muninn"] = {
                        "id": fc.KID,
                        "state": "written",
                        "request_id": fc.RID,
                        "request_window": copy.deepcopy(self.data["request"]["window"]),
                        "project_id": str(self.project),
                        "reason_code": "ok",
                    }
                    self.data["notes"][0]["revision"] = 4
                    self.data["notes"][0]["body"]["content"] = "Keep the revised queue decision visible."
                    expected_request = fc.RID
                    if owner == "same_request":
                        self.data["receipt"]["applied"][0]["revision"] = 4
                    else:
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
                        expected_request = "R_" + "d" * 32
                        detail["request"]["id"] = expected_request
                        detail["receipt"].update(
                            request_id=expected_request, applied=[{"knowledge_id": fc.KID, "revision": 4}]
                        )
                        self.data["requests"] = [self.data["request"], detail["request"]]
                        self.data["extra_details"] = {expected_request: detail}
                    self.save()
                    path = self.root / f"{provider.name}-{owner}/s1/progress.json"
                    path.parent.mkdir(parents=True)
                    path.write_text(json.dumps(state))
                    before = path.read_bytes(), (self.root / "data.json").read_bytes()
                    code, payload = self.cli(provider, "scripts/lib/handoff_derive.py", [str(path), "--session", "s1"])
                    self.assertEqual(code, 3, payload)
                    local = [row for row in payload["decisions"] if row["source"] == "progress"]
                    self.assertEqual(local[0]["reason_code"], "learning_no_matching_record")
                    self.assertIsNone(local[0]["quote"])
                    extra = [row for row in payload["decisions"] if row["source"] == "muninn"]
                    self.assertEqual(
                        [(row["id"], row["revision"], row["request_id"]) for row in extra],
                        [(fc.KID, 4, expected_request)],
                    )
                    self.assertEqual(extra[0]["quote"], fc.QUOTE)
                    self.assertEqual((path.read_bytes(), (self.root / "data.json").read_bytes()), before)
        self.assertEqual(self.submissions(), 0)


if __name__ == "__main__":
    unittest.main()
