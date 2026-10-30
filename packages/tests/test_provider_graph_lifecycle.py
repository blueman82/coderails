"""Verify native lifecycle authority, retry names and stop/resume boundaries."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from hooks.scripts.lib.graph_executor import graph_semantics
from packages.tests.provider_fixture import Provider
from scripts.lib.decision_record import add_decision


def artifacts_with_orders_prepared(provider: Provider) -> None:
    """Run the prepare CLI, then bind its receipt into the final retro assembly."""
    provider.artifacts()
    state_dir = provider.path.parent
    prepared = subprocess.run(
        [
            sys.executable,
            str(provider.plugin / "scripts/lib/orders.py"),
            "--dir",
            str(state_dir.parent),
            "--session",
            provider.session,
            "prepare",
            "--loop",
            provider.read()["loop_id"],
        ],
        capture_output=True,
        text=True,
        check=False,
        env=provider.environment,
        cwd=provider.home,
    )
    if prepared.returncode:
        raise AssertionError(prepared.stderr)
    assembled = subprocess.run(
        [
            sys.executable,
            str(provider.plugin / "scripts/lib/retro.py"),
            "assemble",
            str(state_dir),
            "--session",
            provider.session,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**provider.environment, "PATH": "/nonexistent"},
        cwd=provider.home,
    )
    if assembled.returncode not in (0, 3):
        raise AssertionError(assembled.stderr)


class ProviderLifecycleTests(unittest.TestCase):
    """Exercise hook routes separately from pure graph transitions."""

    def setUp(self) -> None:
        """Create isolated native fixtures."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.providers = [Provider(Path(temporary.name), name) for name in ("claude", "codex")]

    def denied(self, provider: Provider, request: dict[str, Any]) -> None:
        """Require a real native hook denial without durable graph mutation."""
        before = provider.path.read_bytes()
        result = provider.hook("loop_dispatch_guard", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(provider.path.read_bytes(), before)

    def test_recovered_wave_redispatches_under_a_new_attempt_and_completes(self) -> None:
        """Recover, re-dispatch, record done and complete; losing the stale attempt's native spawn breaks completion."""
        for provider in self.providers:
            provider.success("begin-wave")
            provider.launch("stale")
            provider.success("recover-wave", "--session", provider.session, "--lease-seconds", "600")
            first = "wave-2" if provider.name == "claude" else "loop_worker_"
            provider.finish_wave()
            artifacts_with_orders_prepared(provider)
            original = provider.parent.read_text()
            lines = original.splitlines(keepends=True)
            provider.parent.write_text("".join(line for line in lines if first not in line or "_a2" in line))
            self.assertNotEqual(provider.complete().returncode, 0, provider.name)
            provider.parent.write_text(original)
            result = provider.complete()
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_never_dispatched_graph_started_by_start_can_complete(self) -> None:
        """`start` then complete with graded evidence succeeds on both providers; a pending node still blocks."""
        for provider in self.providers:
            provider.path.unlink()
            prompt = provider.home / "prompt.txt"
            prompt.write_text("go")
            provider.success(
                "start", "--session", provider.session, "--loop-id", "fixture-loop", "--prompt-file", str(prompt)
            )
            state = provider.read()
            self.assertEqual((state["stops"], state["state_minor"]), ([], 2))
            self.assertEqual(state["graph"]["wave_history"], {})
            state["graph"].pop("wave_history")  # a graph written by the old `start`, before the key existed
            provider.write(state)
            provider.freeze()
            provider.artifacts()
            result = provider.complete()
            self.assertEqual(result.returncode, 0, (provider.name, result.stderr))
            self.assertEqual(provider.read()["status"], "complete")

    def test_completion_waits_for_hashed_decisions_and_worker_answers(self) -> None:
        """Both native completion commands preserve state until decisions are resolved."""
        for provider in self.providers:
            provider.finish_wave()
            state = provider.read()
            state = add_decision(
                state, provider.session, "2.5", "Use the selected design", state["loop_id"], state["revision"]
            )["state"]
            provider.write(state)
            provider.artifacts()
            for sync in ("syncing", "unknown"):
                state["decisions_absorbed"][0]["muninn"] = {"state": sync}
                provider.write(state)
                before = provider.path.read_bytes()
                result = provider.complete()
                self.assertNotEqual(result.returncode, 0, (provider.name, sync, result.stderr))
                self.assertIn("decision_sync_pending", result.stdout + result.stderr)
                self.assertEqual(provider.path.read_bytes(), before)
            state["decisions_absorbed"][0]["muninn"] = {"state": "written", "id": "K1"}
            state["worker_statuses"] = [
                {"seq": 1, "node": "U3[1]", "status": "NEEDS_DECISION", "decision_pending": True}
            ]
            provider.write(state)
            before = provider.path.read_bytes()
            result = provider.complete()
            self.assertNotEqual(result.returncode, 0, (provider.name, result.stderr))
            self.assertIn("decision_pending:U3[1]", result.stdout + result.stderr)
            self.assertEqual(provider.path.read_bytes(), before)
            state.pop("worker_statuses")
            for sync in ("written", "disabled"):
                state["decisions_absorbed"][0]["muninn"] = (
                    {"state": "written", "id": "K1"} if sync == "written" else {"state": "disabled"}
                )
                self.assertEqual(graph_semantics.can_complete(state), {"eligible": True, "blockers": []})

    def test_empty_graph_rejects_malformed_worker_status_storage(self) -> None:
        """Stored status shape must block completion even without registered nodes."""
        for provider in self.providers:
            provider.path.unlink()
            prompt = provider.home / "prompt.txt"
            prompt.write_text("go")
            provider.success(
                "start", "--session", provider.session, "--loop-id", "fixture-loop", "--prompt-file", str(prompt)
            )
            state = provider.read()
            state["worker_statuses"] = {"unexpected": "object"}
            provider.write(state)
            provider.freeze()
            provider.artifacts()
            self.assertFalse(graph_semantics.can_complete(state)["eligible"])
            before = provider.path.read_bytes()
            result = provider.complete()
            self.assertNotEqual(result.returncode, 0, (provider.name, result.stderr))
            self.assertIn("decision_pending", result.stdout + result.stderr)
            self.assertEqual(provider.path.read_bytes(), before)
            state.pop("worker_statuses")
            provider.write(state)
            self.assertTrue(graph_semantics.can_complete(state)["eligible"])

    def test_empty_graph_rejects_orphan_pending_worker_status(self) -> None:
        """A pending worker answer must block completion even if its node is absent."""
        for provider in self.providers:
            provider.path.unlink()
            prompt = provider.home / "prompt.txt"
            prompt.write_text("go")
            provider.success(
                "start", "--session", provider.session, "--loop-id", "fixture-loop", "--prompt-file", str(prompt)
            )
            state = provider.read()
            state["worker_statuses"] = [
                {"seq": 1, "node": "U3[1]", "status": "NEEDS_DECISION", "decision_pending": True}
            ]
            provider.write(state)
            provider.freeze()
            provider.artifacts()
            self.assertIn("decision_pending:U3[1]", graph_semantics.can_complete(state)["blockers"])
            before = provider.path.read_bytes()
            result = provider.complete()
            self.assertNotEqual(result.returncode, 0, (provider.name, result.stderr))
            self.assertIn("decision_pending:U3[1]", result.stdout + result.stderr)
            self.assertEqual(provider.path.read_bytes(), before)
            state.pop("worker_statuses")
            provider.write(state)
            released = provider.complete()
            self.assertEqual(provider.read()["status"], "complete", (provider.name, released.stdout, released.stderr))

    def test_dispatch_exact_owner_scope_and_retry_name(self) -> None:
        """Foreign ownership and old attempt names cannot authorize a new native worker."""
        for provider in self.providers:
            state = provider.read()
            state["work_units"] = {"unit": {"status": "pending"}}
            provider.write(state)
            provider.success("begin-wave")
            request = provider.request()
            self.assertEqual(provider.hook("loop_dispatch_guard", request).stdout, "")
            altered = copy.deepcopy(request)
            field = "prompt" if provider.name == "claude" else "message"
            altered["tool_input"][field] = (
                altered["tool_input"][field].replace('"node_id": "U3[1]"', '"node_id": "U3[2]"')
                if provider.name == "claude"
                else "CODERAILS_GRAPH_TASK=harmless_reviewer\nImplement."
            )
            self.denied(provider, altered)
            suite = provider.read("evals.json")
            for replacement in ({**suite, "scope": "pr"}, {**suite, "grading": {"by": "forged"}, "result": "GO"}):
                provider.write(replacement, "evals.json")
                self.denied(provider, request)
            provider.write(suite, "evals.json")
            provider.success("record-wave", json.dumps(provider.launch("failed")))
            provider.success("begin-wave")
            second = provider.request()
            self.assertNotEqual(request["tool_input"], second["tool_input"])
            self.denied(provider, request)
            self.assertEqual(provider.hook("loop_dispatch_guard", second).stdout, "")
            provider.success("record-wave", json.dumps(provider.launch()))

    def test_codex_native_tool_boundary_and_missing_active_wave(self) -> None:
        """A Claude alias or absent active wave cannot bypass native ownership."""
        provider = self.providers[1]
        baseline = provider.read()
        provider.success("begin-wave")
        request = provider.request()
        self.denied(provider, {**request, "tool_name": "Agent"})
        altered = copy.deepcopy(request)
        altered["tool_input"].update(task_name="ordinary", message="Read documentation.")
        self.denied(provider, altered)  # a graph-bound session binds every spawn: no envelope, no dispatch
        provider.write(baseline)
        self.denied(provider, request)

    def test_join_disagreement_and_hard_stop_refuse_new_work(self) -> None:
        """An unreleased completed join cannot release downstream work or complete."""
        for provider in self.providers:
            state = provider.state(("U3[1]", "J12-all-units", "S9-wiki"))
            state["graph"]["joins"] = {
                "J12-all-units": {"id": "J12-all-units", "mode": "all", "inputs": ["U3[1]"], "released": False}
            }
            state["graph"]["nodes"]["J12-all-units"].update(status="done", outcome="done")
            state["graph"]["edges"] = [{"from": "J12-all-units", "to": "S9-wiki"}]
            provider.write(state)
            before = provider.path.read_bytes()
            self.assertNotEqual(provider.call("begin-wave").returncode, 0)
            self.assertNotEqual(provider.complete().returncode, 0)
            self.assertEqual(provider.path.read_bytes(), before)
            provider.write(provider.state())
            provider.success(
                "hard-stop", "--node", "U3[1]", "--session", provider.session, "--reason", "owner decision"
            )
            self.assertNotEqual(provider.call("begin-wave").returncode, 0)

    def test_hard_stop_refuses_outside_active_wave_without_changing_state(self) -> None:
        """An unrelated stop cannot advance the revision of dispatched work."""
        for provider in self.providers:
            state = provider.state(("U3[1]", "U3[2]"))
            state["graph"]["nodes"]["U3[2]"].update(status="blocked", outcome="blocked")
            provider.write(state)
            wave = provider.success("begin-wave")
            before = provider.path.read_bytes()
            result = provider.call(
                "hard-stop", "--node", "U3[2]", "--session", provider.session, "--reason", "owner decision"
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(provider.path.read_bytes(), before)
            self.assertEqual(provider.success("inspect")["active_wave"]["wave_id"], wave["wave_id"])

    def test_hard_stop_refuses_surviving_workers_without_retagging(self) -> None:
        """A stop cannot change a surviving worker's wave identity."""
        for provider in self.providers:
            provider.write(provider.state(("U3[1]", "U3[2]")))
            wave = provider.success("begin-wave")
            before = provider.path.read_bytes()
            result = provider.call(
                "hard-stop", "--node", "U3[1]", "--session", provider.session, "--reason", "owner decision"
            )
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertEqual(provider.path.read_bytes(), before)
            self.assertEqual(provider.success("inspect")["active_wave"]["wave_id"], wave["wave_id"])

    def test_hard_stop_singleton_active_wave_persists_valid_state(self) -> None:
        """Stopping the only dispatched node clears its wave and advances revision."""
        for provider in self.providers:
            provider.write(provider.state())
            wave = provider.success("begin-wave")
            provider.success(
                "hard-stop", "--node", "U3[1]", "--session", provider.session, "--reason", "owner decision"
            )
            inspected = provider.success("inspect")
            self.assertIsNone(inspected["active_wave"])
            self.assertEqual(inspected["revision"], wave["revision"] + 1)
            self.assertEqual(inspected["hard_stop"]["node"], "U3[1]")

    def test_codex_stop_and_bootstrap_trust_actual_state(self) -> None:
        """Typed completion does not stop; recorded hard-stop can wait and resumes visibly."""
        provider = self.providers[1]
        state = provider.read()
        state["status"] = "complete"
        provider.write(state)
        payload = {"session_id": provider.session, "cwd": str(provider.home), "last_assistant_message": "complete"}
        result = provider.hook("graph_completion_guard", payload)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        provider.write(provider.state())
        provider.success("hard-stop", "--node", "U3[1]", "--session", provider.session, "--reason", "owner decision")
        text = {**payload, "last_assistant_message": "LOOP-STOP: waiting-on-human"}
        self.assertEqual(json.loads(provider.hook("graph_completion_guard", text).stdout)["decision"], "block")
        provider.success(
            "stop", "--session", provider.session, "--category", "hard-stop",
            "--reason-code", "node_hard_stop", "--reason", "owner decision",
        )  # fmt: skip
        result = provider.hook("graph_completion_guard", payload)
        self.assertEqual(result.stdout, "", result.stderr)
        result = provider.hook("inject_bootstrap", {**payload, "hook_event_name": "SessionStart"})
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("fixture-loop", context)
        self.assertIn("hard_stop", context)


if __name__ == "__main__":
    unittest.main()
