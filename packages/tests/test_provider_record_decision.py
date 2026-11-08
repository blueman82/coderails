"""Both graph CLIs use the same hashed decision writer and status resolution."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast

from packages.tests.provider_fixture import Provider
from packages.tests.test_provider_controller_commands import (
    LOOP,
    SESSION,
    Controller,
    ControllerCase,
)
from scripts.lib import decision_record


def decide(c: Controller, *extra: str, session: str = SESSION) -> subprocess.CompletedProcess[str]:
    """Run the typed command against the current graph revision."""
    return c.run(
        "record-decision",
        "--session",
        session,
        "--loop-id",
        LOOP,
        "--revision",
        str(c.read()["revision"]),
        "--phase",
        "2.6",
        "--decision",
        "disposition",
        *extra,
    )


class RecordDecisionTests(ControllerCase):
    """Check the local commit and refusal boundary through provider CLIs."""

    def started(self, c: Controller) -> None:
        """Use a fixture graph and prevent access to the operator's Muninn binary."""
        c.env["PATH"] = "/usr/bin:/bin"
        self.assertEqual(c.start().returncode, 0)

    def test_hashed_rows_continue_after_legacy_row(self) -> None:
        """A typed write keeps old data and starts one valid chain."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["decisions_absorbed"] = [{"phase": "2.5", "decision": "prior choice"}]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            result = decide(c, "--chosen", "clean-break")
            self.assertEqual(result.returncode, 3, result.stderr)
            rows = c.read()["decisions_absorbed"]
            self.assertEqual(rows[0], {"phase": "2.5", "decision": "prior choice"})
            self.assertEqual(rows[1]["seq"], 2)
            self.assertEqual(rows[1]["chosen"], "clean-break")
            self.assertEqual(rows[1]["prev_sha256"], "0" * 64)
            self.assertEqual(len(rows[1]["row_sha256"]), 64)
            self.assertEqual(rows[1]["muninn"]["state"], "degraded")
            self.assertEqual(c.read()["chain_started_seq"], 2)

    def test_status_and_hash_commit_together_but_sync_still_blocks(self) -> None:
        """One decision resolves the named status without opening the next wave on failed sync."""
        for c in self.each():
            self.started(c)
            state = c.read()
            state["worker_statuses"] = [
                {
                    "seq": 1,
                    "node": "U3[1]",
                    "status": "NEEDS_DECISION",
                    "payload": {"options": ["allow", "deny"]},
                    "decision_pending": True,
                }
            ]
            c.path.write_text(json.dumps(state), encoding="utf-8")
            result = decide(c, "--chosen", "allow", "--worker-status-seq", "1")
            self.assertEqual(result.returncode, 3, result.stderr)
            current = c.read()
            self.assertEqual(current["worker_statuses"][0]["resolved_by_decision"], 1)
            self.assertFalse(current["worker_statuses"][0]["decision_pending"])
            self.assertEqual(current["decisions_absorbed"][0]["worker_status_seq"], 1)
            self.assertEqual(current["decisions_absorbed"][0]["chosen"], "allow")

    def test_refusal_preserves_bytes(self) -> None:
        """Wrong owner, blank answer and unknown status do not modify the graph."""
        for c in self.each():
            self.started(c)
            cases = (
                (decide(c, session="foreign"), "decision_wrong_session"),
                (decide(c, "--chosen", " "), "record_decision_refused_field"),
                (
                    decide(c, "--chosen", "yes", "--worker-status-seq", "9"),
                    "record_decision_refused_status",
                ),
            )
            for result, reason in cases:
                before = c.path.read_bytes()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)["reason_code"], reason)
                self.assertEqual(c.path.read_bytes(), before)


class DecisionConsumerIntegrityTests(unittest.TestCase):
    """Check real writer rows at source consumers without native completion claims."""

    def setUp(self) -> None:
        """Keep every input in its own provider home and repository."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.count = 0

    def recorded(self, name: str, *, active: bool = False, legacy: bool = False) -> tuple[Provider, dict[str, Any]]:
        """Use the real CLI with memory off, then isolate the consumer's graph state."""
        self.count += 1
        root = self.root / str(self.count)
        root.mkdir()
        provider = Provider(root, name)
        if legacy:
            state = provider.read()
            state["decisions_absorbed"] = [{"phase": "prior", "decision": "Retain an earlier prose row."}]
            provider.write(state)
        if active:
            dispatch = provider.success("begin-wave")["dispatches"][0]
            provider.path.with_name("decision-prompt.txt").write_text(
                dispatch["prompt_prefix"] + "\n" + dispatch["prompt_sections"],
                encoding="utf-8",
            )
        state = provider.read()
        result = provider.call(
            "record-decision",
            "--session",
            provider.session,
            "--loop-id",
            state["loop_id"],
            "--revision",
            str(state["revision"]),
            "--phase",
            "implementation",
            "--decision",
            "Keep the assigned source unchanged.",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        state = provider.read()
        self.assertEqual(state["decisions_absorbed"][-1]["muninn"]["state"], "disabled")
        if not active:
            # This is eligibility input, not a native terminal receipt or complete command.
            for node in state["graph"]["nodes"].values():
                node.update(status="done", outcome="done")
            state["work_units"] = {}
        return provider, state

    @staticmethod
    def edit(state: dict[str, Any], case: str) -> None:
        """Change content without rehashing, or only the explicitly mutable sync field."""
        row = state["decisions_absorbed"][-1]
        if case == "changed-text":
            row["decision"] += " Altered after the writer saved its hash."
        elif case == "added-session":
            row["session_id"] = "another-session"
        elif case == "mutable-sync":
            row["muninn"]["reason_code"] = "explicit_backend_disabled"
        elif case == "generic-degraded":
            row["muninn"] = {
                "state": "degraded",
                "id": None,
                "reason_code": "muninn_absent",
            }

    def consumer(self, provider: Provider, script: str) -> dict[str, Any]:
        """Run the selected real provider module in a separate process."""
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                script,
                str(provider.plugin / "skills/agentic-loop/scripts"),
                str(provider.path),
            ],
            cwd=provider.checkout,
            env=provider.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return cast(dict[str, Any], json.loads(process.stdout))

    def test_writer_integrity_at_readiness_and_standalone_orders(self) -> None:
        """Changed typed rows refuse independently of the memory backend or native history."""
        script = (
            "import sys,json;sys.path.insert(0,sys.argv[1]);import graph_semantics;"
            "print(json.dumps(graph_semantics.can_complete(json.load(open(sys.argv[2])))))"
        )
        for name in ("claude", "codex"):
            for case in (
                "disabled",
                "legacy",
                "mutable-sync",
                "generic-degraded",
                "changed-text",
                "added-session",
            ):
                with self.subTest(provider=name, case=case):
                    provider, state = self.recorded(name, legacy=case == "legacy")
                    self.edit(state, case)
                    provider.write(state)
                    before = provider.path.read_bytes()
                    ready = self.consumer(provider, script)
                    orders = subprocess.run(
                        [
                            sys.executable,
                            str(provider.plugin / "scripts/lib/orders.py"),
                            "--dir",
                            str(provider.path.parent.parent),
                            "--session",
                            provider.session,
                            "prepare",
                            "--loop",
                            state["loop_id"],
                        ],
                        cwd=provider.checkout,
                        env=provider.environment,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    payload = json.loads(orders.stdout)
                    invalid = case in ("changed-text", "added-session")
                    with self.subTest(consumer="readiness"):
                        self.assertEqual(ready["eligible"], not invalid, ready)
                    with self.subTest(consumer="orders"):
                        self.assertEqual(orders.returncode, 2 if invalid else 0, payload)
                        if invalid:
                            self.assertIn(
                                payload["reason_code"],
                                ("order_loop_ineligible", "order_source_invalid"),
                            )
                            self.assertEqual(
                                list(provider.path.parent.glob("orders-prepared-*.json")),
                                [],
                            )
                        else:
                            self.assertTrue(payload["prepared"])
                    self.assertEqual(provider.path.read_bytes(), before)

    def test_writer_integrity_at_live_dispatch(self) -> None:
        """An issued real contract accepts matching rows and refuses stale content hashes."""
        script = """
import sys,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import graph_contract
state=json.load(open(sys.argv[2]))
prompt=Path(sys.argv[2]).with_name('decision-prompt.txt').read_text()
try:
    graph_contract.check_dispatch(state,graph_contract.parse_envelope(prompt),prompt,live=True)
except graph_contract.DispatchDeniedError as error:
    print(json.dumps({'accepted':False,'code':error.code}))
else:
    print(json.dumps({'accepted':True}))
"""
        for name in ("claude", "codex"):
            for case in ("disabled", "mutable-sync", "changed-text", "added-session"):
                with self.subTest(provider=name, case=case):
                    provider, state = self.recorded(name, active=True)
                    self.edit(state, case)
                    provider.write(state)
                    before = provider.path.read_bytes()
                    result = self.consumer(provider, script)
                    invalid = case in ("changed-text", "added-session")
                    self.assertEqual(result["accepted"], not invalid, result)
                    if invalid:
                        self.assertTrue(result["code"])
                    self.assertEqual(provider.path.read_bytes(), before)


class DecisionChainGoldenTests(unittest.TestCase):
    """Retain a saved hash while mutable sync states change."""

    def test_saved_hash_is_stable_across_mutable_sync(self) -> None:
        """The literal hash predates extraction and is not computed by the new verifier."""
        row: dict[str, Any] = {
            "seq": 1,
            "phase": "qualify-generic",
            "decision": "Keep this synthetic checkout bound f497085bd31a491c89cf08f3e7dcbfd5",
            "flip_condition": None,
            "unit": None,
            "revision": 3,
            "ts": "2026-11-06T06:01:15+00:00",
            "prev_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        }
        expected = "6d395607296c18912698b53e18adf7b7df672259b35672b49d1f90d958eb0161"
        row["row_sha256"] = expected
        for state in ("syncing", "pending", "written", "disabled", "degraded"):
            with self.subTest(state=state):
                row["muninn"] = {"state": state, "id": None, "reason_code": "mutable"}
                self.assertEqual(decision_record.row_digest(row), expected)
                decision_record.ensure_chain({"decisions_absorbed": [row], "chain_started_seq": 1})
