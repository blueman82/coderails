"""Verify native lifecycle authority, retry names and stop/resume boundaries."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import Provider


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
        self.assertEqual(provider.hook("loop_dispatch_guard", altered).stdout, "")
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
        result = provider.hook(
            "graph_completion_guard", {**payload, "last_assistant_message": "LOOP-STOP: waiting-on-human"}
        )
        self.assertEqual(result.stdout, "", result.stderr)
        result = provider.hook("inject_bootstrap", {**payload, "hook_event_name": "SessionStart"})
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("fixture-loop", context)
        self.assertIn("hard_stop", context)


if __name__ == "__main__":
    unittest.main()
