"""Preserve first-dispatch frozen eval gates and exact provider-native ownership."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import resolve_path
from hooks.scripts.loop_dispatch_guard import check
from hooks.scripts.tests.claude_graph_test_support import ROOT, GraphCase, dispatch, fixture, load, node
from scripts.post_evals import grade_loop


class DispatchGuardTests(GraphCase):
    """Use current graph state while replacing only obsolete legacy acceptance cases."""

    def setup_request(self, identifier: str = "U3[1]", units: int = 1) -> dict[str, Any]:
        """Open a real wave, then seed planned work units for the dispatch gate."""
        self.path = resolve_path(str(self.home), "fixture-session")
        state = fixture.state(0)
        state["graph"]["nodes"] = {identifier: node(identifier)}
        self.save(state)
        state = self.opened()
        state["work_units"] = {f"unit-{number}": {"status": "pending"} for number in range(units)}
        self.save(state)
        owner = dispatch.ownership(state, identifier)
        return {
            "tool_name": "Agent",
            "session_id": "fixture-session",
            "cwd": str(self.home),
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "CODERAILS_GRAPH_DISPATCH=" + json.dumps(owner) + "\nWorker instructions.",
            },
        }

    def frozen(self) -> dict[str, Any]:
        """Write a true ungraded scripted suite with all freeze-time fields."""
        suite = fixture.frozen_evals()
        suite["evals"][0].update(mode="scripted", cmd="true", negative_control="false")
        fixture.write_json(self.path.with_name("evals.json"), suite)
        return suite

    def denied(self, request: dict[str, Any], reason: str = ".") -> None:
        """Name the refusal while pinning zero durable progress changes."""
        before = self.path.read_bytes() if self.path.exists() else None
        with self.assertRaisesRegex(ValueError, reason):
            check(request)
        self.assertEqual(before, self.path.read_bytes() if self.path.exists() else None)

    def test_tool_and_nonloop_scope_without_session_lockout(self) -> None:
        """Unrelated calls stay free; graph-marked and implementation calls need owned state."""
        request: dict[str, Any] = {
            "tool_name": "Agent",
            "session_id": "fixture-session",
            "cwd": str(self.home),
            "tool_input": {"subagent_type": "general-purpose"},
        }
        check(request)
        request["tool_input"]["subagent_type"] = "coderails:loop-worker"
        self.denied(request, "no owned progress")
        request["tool_name"] = "Bash"
        request["tool_input"]["command"] = "ls"
        check(request)
        request = self.setup_request(units=0)
        check(request)
        request["tool_name"] = "Bash"
        request["tool_input"]["command"] = "ls"
        check(request)
        request["tool_name"] = "Agent"
        self.path.unlink()
        self.denied(request, "no owned progress")

    def test_roster_threshold_and_frozen_first_dispatch(self) -> None:
        """One, three and five entirely pending work units gate their very first worker."""
        for units in (1, 3, 5):
            request = self.setup_request(units=units)
            self.path.with_name("evals.json").unlink(missing_ok=True)
            self.denied(request, "frozen eval|another session")
            self.frozen()
            check(request)
        request = self.setup_request(units=0)
        self.path.with_name("evals.json").unlink()
        check(request)

    def test_exact_owner_and_provider_role(self) -> None:
        """Native roles are allowed while wrong session/loop/node/wave/revision deny."""
        request = self.setup_request()
        self.frozen()
        for role in ("general-purpose", "Plan", "coderails:loop-worker"):
            request["tool_input"]["subagent_type"] = role
            check(request)
        original = copy.deepcopy(request)
        for key, value in (
            ("session_id", "foreign"),
            ("loop_id", "foreign"),
            ("node_id", "U3[2]"),
            ("wave_id", "wave-99"),
            ("revision", 99),
        ):
            request = copy.deepcopy(original)
            owner = dispatch.ownership(load(self.path), "U3[1]")
            owner[key] = value
            request["tool_input"]["prompt"] = "CODERAILS_GRAPH_DISPATCH=" + json.dumps(owner)
            self.denied(request, "envelope")
        for prompt in ("", "CODERAILS_GRAPH_DISPATCH={}", "prefix CODERAILS_GRAPH_DISPATCH={}"):
            request = copy.deepcopy(original)
            request["tool_input"]["prompt"] = prompt
            self.denied(request, "envelope")
        request = copy.deepcopy(original)
        request["tool_input"]["subagent_type"] = ""
        self.denied(request, "provider subagent_type")
        for key in ("loop_id", "revision"):
            state = load(self.path)
            del state[key]
            self.save(state)
            self.denied(original)
            self.setup_request()
            self.frozen()

    def test_freeze_field_negative_controls(self) -> None:
        """Every freeze-time discriminator independently rejects an otherwise valid suite."""
        request = self.setup_request()
        original = self.frozen()
        variants: list[dict[str, Any]] = []
        changes: tuple[tuple[str, Any], ...] = (
            ("session_id", "foreign"),
            ("loop_id", "foreign"),
            ("scope", "pr"),
            ("verification_level", "2"),
            ("verification_justification", "   "),
            ("frozen_sha", ""),
            ("evals", []),
            ("result", "GO"),
            ("grading", {"by": "post_evals.py grade-loop", "checksum": "fake"}),
        )
        for key, value in changes:
            variants.append({**original, key: value})
        for key, value in (
            ("priority", "P1"),
            ("mode", "handwave"),
            ("id", ""),
            ("cmd", ""),
            ("negative_control", "   "),
        ):
            variant = copy.deepcopy(original)
            variant["evals"][0][key] = value
            variants.append(variant)
        variants.append(
            {
                "scope": "loop",
                "session_id": "fixture-session",
                "loop_id": "fixture-loop",
                "verification_level": 2,
                "verification_justification": "x",
                "evals": [{"priority": "P0"}],
            }
        )
        path = self.path.with_name("evals.json")
        for value in variants:
            with self.subTest(value=value):
                fixture.write_json(path, value)
                self.denied(request)
        path.write_text("not json")
        self.denied(request)
        fixture.write_json(path, original)
        check(request)
        original["evals"][0].update(mode="agent-run", cmd="", negative_control="")
        fixture.write_json(path, original)
        check(request)

    def test_graded_and_frozen_prior_revision_remain_valid_at_dispatch(self) -> None:
        """Dispatch binds stable identity rather than invalidating evals on every wave."""
        request = self.setup_request()
        suite = self.frozen()
        self.assertLess(suite["revision"], load(self.path)["revision"])
        check(request)
        suite["evals"][0].update(status="pass", evidence="verified")
        suite["head_sha"] = "a" * 40
        fixture.write_json(self.path.with_name("evals.json"), suite)
        grade_loop(self.path.with_name("evals.json"))
        graded = json.loads(self.path.with_name("evals.json").read_text())
        check(request)
        suite.update(verification_level=0, evals=[])
        fixture.write_json(self.path.with_name("evals.json"), suite)
        grade_loop(self.path.with_name("evals.json"))
        check(request)
        self.assertEqual(graded["result"], "GO")

    def test_prefreeze_bootstrap_and_downstream_native_roles(self) -> None:
        """Eval authors can run before freeze; every downstream native role remains gated."""
        for identifier in ("S2", "S2.7c", "S2.7e"):
            request = self.setup_request(identifier)
            self.path.with_name("evals.json").unlink(missing_ok=True)
            check(request)
            request["tool_input"]["subagent_type"] = "coderails:loop-worker"
            self.denied(request)
        for identifier in ("S9-wiki", "S9-docs", "U3[1]"):
            request = self.setup_request(identifier)
            self.denied(request)
            self.frozen()
            check(request)
            self.path.with_name("evals.json").unlink()
        state = load(self.path)
        for version in (1, 2):
            self.save({**state, "schema_version": version})
            self.denied(request, "schema_version must be 3")

    def test_native_hook_denial_exit_and_logging(self) -> None:
        """PreToolUse denial stays one native JSON decision, exit zero, and audited."""
        request = self.setup_request()
        before = self.path.read_bytes()
        result = subprocess.run(
            [sys.executable, str(ROOT / "hooks/scripts/loop_dispatch_guard.py")],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=False,
            env=os.environ,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(before, self.path.read_bytes())
        self.assertIn("hook=loop_dispatch_guard blocked=1", (self.home / "discipline.log").read_text())


if __name__ == "__main__":
    unittest.main()
