"""Exercise current requests and read-only handoff against public-shaped CLI views."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib.dir_lock import acquire_dir_lock, release_dir_lock  # noqa: E402
from hooks.scripts.lib.graph_executor import transition  # noqa: E402
from hooks.scripts.tests.lib import claude_transcript_fixture as graph_fixture  # noqa: E402
from scripts.lib import decision_record as dr  # noqa: E402
from scripts.lib import handoff_derive, lessons  # noqa: E402
from scripts.lib import orders_ledger as ol  # noqa: E402
from scripts.tests import fake_muninn_current as fc  # noqa: E402
from scripts.tests.orders_lifecycle_test import progress  # noqa: E402


class CurrentFixture(unittest.TestCase):
    """A mapped project, physical originals, and graph state in distinct directories."""

    def setUp(self) -> None:
        """Keep every external call inside a disposable mapped repository."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.data: dict[str, Any] = fc.fixture(self.root, self.project)
        self.save()
        binary = self.root / "muninn"
        binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fc.__file__}" "$@"\n')
        binary.chmod(0o700)
        patch = mock.patch.dict(
            os.environ,
            {
                "CURRENT_MUNINN_FIXTURE": str(self.root),
                "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
                "CLAUDE_AGENTIC_LOOP_DIR": str(self.root / "trace"),
            },
        )
        patch.start()
        self.addCleanup(patch.stop)
        previous = Path.cwd()
        os.chdir(self.project)
        self.addCleanup(os.chdir, previous)

    def save(self) -> None:
        """Publish one controlled transport response."""
        (self.root / "data.json").write_text(json.dumps(self.data))


class CurrentConsumers(CurrentFixture):
    """Exercise retained requests at the actual consumer boundaries."""

    def test_decision_submission_is_pending_and_keeps_request_binding(self) -> None:
        """An accepted request cannot become a saved K-id without its later receipt."""
        self.data["request"]["state"] = "pending"
        self.data["receipt"] = None
        self.save()
        result = dr.sync_row({"phase": "2.5", "decision": "choose the bronze queue"}, "L1", "s1", "ignored")
        self.assertEqual(result["state"], "pending", result)
        self.assertEqual(result["request_id"], fc.RID)
        self.assertEqual(result["project_id"], str(self.project))
        self.assertEqual(result["request_window"], self.data["request"]["window"])

    def test_handoff_reads_bound_local_and_extra_current_decisions_without_writes(self) -> None:
        """Legacy listing or dropping supported external task Notes loses handoff decisions."""
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
        extra = json.loads(json.dumps(self.data["notes"][0]))
        extra["id"] = "K_" + "6" * 32
        extra["body"]["content"] = "Keep the independent external decision."
        self.data["notes"].append(extra)
        self.data["receipt"]["applied"].append({"knowledge_id": extra["id"], "revision": 3})
        broad = json.loads(json.dumps(extra))
        broad["id"] = "K_" + "7" * 32
        broad["body"]["scope"]["task"] = None
        self.data["notes"].insert(0, broad)
        self.save()
        before = (self.root / "data.json").read_bytes()
        degraded: list[dict[str, str]] = []
        rows = handoff_derive.decisions(state, "L1", "s1", degraded)
        self.assertEqual(degraded, [])
        self.assertEqual({r["id"] for r in rows}, {fc.KID, extra["id"]})
        self.assertTrue(all(r["quote"] == fc.QUOTE and r["revision"] == 3 for r in rows))
        self.assertEqual((self.root / "data.json").read_bytes(), before)
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertTrue(all(call["args"][:2] != ["learn", "request"] for call in calls))
        self.assertTrue(all(call["cwd"] == str(self.project) for call in calls))

    def test_lesson_query_and_handoff_keep_conditions_and_refuse_unconditional_dispatch(self) -> None:
        """A conditional saved lesson must not flatten into an unconditional contract or promotion."""
        self.data = fc.fixture(self.root, self.project, kind="lesson", claim="Use the bronze queue.")
        self.data["notes"][0]["body"]["conditions"] = ["Only after owner approval."]
        self.data["notes"][0]["expiry"] = {"at": None, "condition": "Until release ends.", "evidence_refs": [fc.EID]}
        self.save()
        directory = self.root / "state-key"
        directory.mkdir()
        ledger = ol.record(
            ol.empty(), "queue", "Use the bronze queue.", session_id="s1", loop_id="L1", now="2026-11-05T00:00:00+00:00"
        )["ledger"]
        field = {
            "state": "written",
            "id": fc.KID,
            "request_id": fc.RID,
            "task": "L1",
            "request_window": self.data["request"]["window"],
            "project_id": str(self.project),
            "reason_code": "ok",
        }
        ledger = ol.set_muninn(ledger, "queue", field)
        ol.save(directory / "orders.json", ledger)
        got = lessons.joined(ledger)
        self.assertNotIn("degraded", got)
        self.assertEqual(got["lessons"][0]["body"]["conditions"], ["Only after owner approval."])
        payload, code = lessons.query_contract(directory, "s1")
        self.assertEqual(code, 3)
        self.assertEqual(payload["degraded"], "learning_conditional_use_unsupported")
        degraded: list[dict[str, str]] = []
        handoff = handoff_derive.lesson_rows(directory, degraded)
        self.assertEqual(handoff[0]["expiry"]["condition"], "Until release ends.")
        self.assertFalse(handoff[0]["use_allowed"])
        self.assertEqual((directory / "orders.json").read_text(), json.dumps(ledger, indent=1, sort_keys=True) + "\n")

    def test_order_cli_saves_request_before_receipt_and_recovers_same_request(self) -> None:
        """A restart must inspect its retained request, preserving the authored order hash."""
        self.data = fc.fixture(self.root, self.project, kind="lesson", claim="Use the bronze queue.")
        self.data["request"]["state"] = "pending"
        self.data["receipt"] = None
        self.save()
        directory = self.root / "state-key"
        directory.mkdir()
        progress(directory, "s1", "L1")
        command = [sys.executable, str(ROOT / "scripts/lib/orders.py"), "--dir", str(directory), "--session", "s1"]
        run = subprocess.run(
            command
            + [
                "record",
                "--id",
                "queue",
                "--failure-mode",
                "queue",
                "--lesson",
                "Use the bronze queue.",
                "--loop",
                "L1",
                "--quote",
                "ignored",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
        first = json.loads(run.stdout)
        self.assertEqual(first["muninn"]["state"], "pending")
        self.assertTrue(first["quote_ignored"])
        before = ol.open_ledger(directory)["orders"][0]["row_sha256"]
        self.data = fc.fixture(self.root, self.project, kind="lesson", claim="Use the bronze queue.")
        self.save()
        run = subprocess.run(command + ["cite", "queue"], capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        saved = json.loads(run.stdout)
        self.assertEqual((saved["muninn"]["id"], saved["muninn"]["revision"]), (fc.KID, 3))
        self.assertEqual(ol.open_ledger(directory)["orders"][0]["row_sha256"], before)
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(
            sum(call["args"][:2] == ["learn", "request"] and "--help" not in call["args"] for call in calls), 1
        )

    def test_unknown_bound_decision_recovers_without_resubmission(self) -> None:
        """Unknown with a retained request is recoverable by inspect, never another submit."""
        directory = self.root / "state-key"
        directory.mkdir()
        path = progress(directory, "s1", "L1", "in-progress")
        completed = self.data["receipt"]
        self.data["request"]["state"] = "pending"
        self.data["receipt"] = None
        self.save()
        first = dr.record(
            path,
            "s1",
            "2.5",
            "choose the bronze queue",
            expected_loop_id="L1",
            expected_revision=1,
            transition=transition,
        )
        self.assertEqual(first["muninn"]["state"], "pending", first)
        state = json.loads(path.read_text())
        state["decisions_absorbed"][0]["muninn"]["state"] = "unknown"
        path.write_text(json.dumps(state))
        self.data["request"]["state"] = "completed"
        self.data["receipt"] = completed
        self.save()
        result = dr.flush_pending(path, "s1", transition=transition)
        self.assertEqual(result["exit_code"], 0, result)
        calls = [json.loads(line)["args"] for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(sum(args[:2] == ["learn", "request"] and "--help" not in args for args in calls), 1)

    def test_order_timeout_marker_survives_two_restarts(self) -> None:
        """A submission that times out without an R-id must not be submitted twice."""
        directory = self.root / "state-key"
        directory.mkdir()
        progress(directory, "s1", "L1")
        self.data["submit_delay"] = 2.0
        self.save()
        program = "from scripts.lib import orders,memory_adapter; memory_adapter.TIMEOUT=.8; orders.main()"
        command = [sys.executable, "-c", program, "--dir", str(directory), "--session", "s1"]
        environment = {**os.environ, "PYTHONPATH": str(ROOT)}
        run = subprocess.run(
            command
            + [
                "record",
                "--id",
                "queue",
                "--failure-mode",
                "queue",
                "--lesson",
                "Use the bronze queue.",
                "--loop",
                "L1",
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )
        field = json.loads(run.stdout)["muninn"]
        self.assertEqual(field["state"], "unknown", run.stdout + run.stderr)
        self.assertIsNone(field["request_id"])
        for _ in range(2):
            retry = subprocess.run(
                command + ["cite", "queue"], env=environment, capture_output=True, text=True, timeout=10
            )
            self.assertEqual(json.loads(retry.stdout)["muninn"]["state"], "unknown")
        calls = [json.loads(line)["args"] for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(sum(args[:2] == ["learn", "request"] and "--help" not in args for args in calls), 1)

    def test_both_provider_graph_commands_and_handoff_use_current_receipt(self) -> None:
        """The actual graph record/flush/handoff commands must carry one same-R current revision."""
        for provider in (ROOT, ROOT / "packages/codex"):
            directory = self.root / ("codex-state" if provider.name == "codex" else "claude-state")
            path = directory / "s1/progress.json"
            path.parent.mkdir(parents=True)
            state = {**graph_fixture.state(), "session_id": "s1", "loop_id": "L1", "authorising_prompt_raw": fc.QUOTE}
            path.write_text(json.dumps(state))
            lock = Path(f"{path}.lock")
            kind = "flock" if provider.name == "codex" else "directory"
            self.data["graph_locks"] = [{"path": str(lock), "kind": kind}]
            self.save()
            # The transport's independent competitor must detect the actual held primitive.
            if kind == "directory":
                acquired, _ = acquire_dir_lock(lock, 1, 0)
                self.assertTrue(acquired)
                try:
                    negative = subprocess.run(
                        ["muninn", "know", "list", "--task", "L1"], capture_output=True, text=True, timeout=10
                    )
                finally:
                    release_dir_lock(lock)
            else:
                with lock.open("a+") as held:
                    fcntl.flock(held, fcntl.LOCK_EX)
                    negative = subprocess.run(
                        ["muninn", "know", "list", "--task", "L1"], capture_output=True, text=True, timeout=10
                    )
            self.assertEqual((negative.returncode, json.loads(negative.stdout)), (2, {"error": "graph_lock_held"}))
            command = [sys.executable, str(provider / "skills/agentic-loop/scripts/graph.py")]
            run = subprocess.run(
                command
                + [
                    "record-decision",
                    str(path),
                    "--session",
                    "s1",
                    "--loop-id",
                    "L1",
                    "--revision",
                    str(state["revision"]),
                    "--phase",
                    "2.5",
                    "--decision",
                    "choose the bronze queue",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(run.returncode, 3, run.stdout + run.stderr)
            self.assertEqual(json.loads(run.stdout)["muninn"]["request_id"], fc.RID)
            run = subprocess.run(
                command + ["flush-decisions", str(path), "--session", "s1"], capture_output=True, text=True, timeout=15
            )
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            handoff = subprocess.run(
                [sys.executable, str(provider / "scripts/lib/handoff_derive.py"), str(path), "--session", "s1"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            payload = json.loads(handoff.stdout)
            self.assertEqual(handoff.returncode, 0, handoff.stdout + handoff.stderr)
            self.assertEqual(payload["degraded"], [])
            self.assertEqual(
                [(row["id"], row["revision"], row["quote"]) for row in payload["decisions"]], [(fc.KID, 3, fc.QUOTE)]
            )


if __name__ == "__main__":
    unittest.main()
