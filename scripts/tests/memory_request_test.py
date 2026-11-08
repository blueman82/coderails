"""Retained recovery identity and newly authored source requests through the real order CLI."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest

from scripts.lib import orders_ledger as ol
from scripts.tests import fake_muninn_current as fc
from scripts.tests.current_consumers_test import ROOT, CurrentFixture
from scripts.tests.orders_lifecycle_test import progress


class RequestIdentity(CurrentFixture):
    """A retry caller and an authored source change have different request consequences."""

    def test_unknown_no_request_cite_from_another_caller_preserves_source_observation(self) -> None:
        """A different recovery caller cannot repeat a request that may already exist."""
        for provider in (ROOT, ROOT / "packages/codex"):
            for changed_claim in (False, True):
                with self.subTest(provider=provider, changed_claim=changed_claim):
                    directory = self.root / f"state-{provider.name}-{changed_claim}"
                    directory.mkdir()
                    claim = "Use a different queue." if changed_claim else "Use the bronze queue."
                    ledger = ol.record(
                        ol.empty(), "queue", claim, session_id="source-old", loop_id="L1", now=ol.now_iso()
                    )["ledger"]
                    previous = {
                        "state": "unknown",
                        "id": None,
                        "request_id": None,
                        "source_session": "source-old",
                        "task": "L1",
                        "claim_sha256": hashlib.sha256(b"Use the bronze queue.").hexdigest(),
                        "reason_code": "muninn_timeout",
                    }
                    ol.save(directory / "orders.json", ol.set_muninn(ledger, "queue", previous))
                    command = [
                        sys.executable,
                        str(provider / "scripts/lib/orders.py"),
                        "--dir",
                        str(directory),
                        "--session",
                        "caller-new",
                        "cite",
                        "queue",
                    ]
                    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
                    field = json.loads(result.stdout)["muninn"]
                    self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                    for key, value in previous.items():
                        self.assertEqual(field[key], value, field)
                    if changed_claim:
                        self.assertEqual(field["reconciliation_reason"], "learning_request_unknown")
                    self.assertEqual(ol.open_ledger(directory)["orders"][0]["muninn"], field)
        path = self.root / "calls.jsonl"
        calls = [json.loads(line)["args"] for line in path.read_text().splitlines()] if path.exists() else []
        self.assertFalse(any(args[:2] == ["learn", "request"] and "--help" not in args for args in calls))

    def test_unknown_claim_change_cannot_resubmit_the_same_source_task(self) -> None:
        """Claim text is absent from request arguments and cannot distinguish an unknown submission."""
        self.data["submit_delay"] = 2.0
        self.save()
        directory = self.root / "state-key"
        directory.mkdir()
        progress(directory, "s1", "L1")
        program = "from scripts.lib import orders,memory_adapter as ma; ma.TIMEOUT=.8; raise SystemExit(orders.main())"
        prefix = [
            sys.executable,
            "-c",
            program,
            "--dir",
            str(directory),
            "--session",
            "s1",
            "record",
            "--id",
            "queue",
            "--failure-mode",
            "queue",
            "--loop",
            "L1",
            "--lesson",
        ]
        environment = {**os.environ, "PYTHONPATH": str(ROOT)}
        original = subprocess.run(
            prefix + ["Use the bronze queue."], env=environment, capture_output=True, text=True, timeout=10
        )
        previous = json.loads(original.stdout)["muninn"]
        self.assertEqual(previous["claim_sha256"], hashlib.sha256(b"Use the bronze queue.").hexdigest())
        changed = subprocess.run(
            prefix + ["Use a different queue."], env=environment, capture_output=True, text=True, timeout=10
        )
        field = json.loads(changed.stdout)["muninn"]
        calls = [json.loads(line)["args"] for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(sum(args[:2] == ["learn", "request"] and "--help" not in args for args in calls), 1)
        self.assertEqual((changed.returncode, field["state"], field["request_id"]), (3, "unknown", None))
        self.assertEqual(field["claim_sha256"], previous["claim_sha256"])
        self.assertEqual(field["reason_code"], previous["reason_code"])
        self.assertEqual(field["reconciliation_reason"], "learning_request_unknown")

    def test_order_cite_from_another_session_inspects_original_source_request(self) -> None:
        """A new reader session does not replace the authored order's retained request identity."""
        self.data = fc.fixture(self.root, self.project, kind="lesson", claim="Use the bronze queue.")
        self.save()
        directory = self.root / "state-key"
        directory.mkdir()
        progress(directory, "s1", "L1")
        prefix = [sys.executable, str(ROOT / "scripts/lib/orders.py"), "--dir", str(directory)]
        first = subprocess.run(
            prefix
            + [
                "--session",
                "s1",
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
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        result = subprocess.run(
            prefix + ["--session", "another-caller", "cite", "queue"], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        field = json.loads(result.stdout)["muninn"]
        self.assertEqual((field["request_id"], field["source_session"]), (fc.RID, "s1"))
        calls = [json.loads(line)["args"] for line in (self.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual(sum(args[:2] == ["learn", "request"] and "--help" not in args for args in calls), 1)

    def test_order_record_new_source_saves_new_unknown_marker_before_request(self) -> None:
        """An authored source/task change must not reuse the earlier request window."""
        self.data = fc.fixture(self.root, self.project, kind="lesson", claim="Use the bronze queue.")
        self.save()
        directory = self.root / "state-key"
        directory.mkdir()
        progress(directory, "s1", "L1")
        prefix = [sys.executable, str(ROOT / "scripts/lib/orders.py"), "--dir", str(directory)]
        authored = ["record", "--id", "queue", "--failure-mode", "queue", "--lesson", "Use the bronze queue."]
        first = subprocess.run(
            prefix + ["--session", "s1", *authored, "--loop", "L1"], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(first.returncode, 3, first.stdout + first.stderr)
        old_window = self.data["request"]["window"].copy()
        progress(directory, "s2", "L2")
        self.data["request"].update(id="R_" + "9" * 32, state="pending")
        self.data["request"]["scope"]["task"] = "L2"
        self.data["request"]["window"] = {**old_window, "source": {"provider": "codex", "thread_id": "s2"}}
        self.data["receipt"] = None
        self.data["marker_probe"] = str(
            directory / "s2" / ("orders-prepared-" + hashlib.sha256(b"L2").hexdigest() + ".json")
        )
        self.save()
        second = subprocess.run(
            prefix + ["--session", "s2", *authored, "--loop", "L2"], capture_output=True, text=True, timeout=15
        )
        self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
        field = json.loads(second.stdout)["muninn"]
        self.assertEqual((field["request_id"], field["task"], field["source_session"]), ("R_" + "9" * 32, "L2", "s2"))
        self.assertNotEqual(field["request_window"], old_window)
        calls = [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]
        submitted = [call for call in calls if "marker_before_submit" in call]
        self.assertEqual(len(submitted), 1)
        marker = submitted[0]["marker_before_submit"]
        self.assertEqual(
            (marker["state"], marker["request_id"], marker["task"], marker["source_session"]),
            ("unknown", None, "L2", "s2"),
        )


if __name__ == "__main__":
    unittest.main()
