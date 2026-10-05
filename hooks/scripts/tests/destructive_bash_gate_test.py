#!/usr/bin/env python3
"""Replay every established destructive-hook behavior against the Python entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.destructive_routes import ROUTES

HOOK = Path(__file__).resolve().parents[1] / "destructive_bash_gate.py"
FIXTURES = Path(__file__).with_name("fixtures") / "destructive_commands"


class DestructiveGateTests(unittest.TestCase):
    """Retain core, tabs, IFS, allowlist, workflow-substitution, and pattern-ID coverage."""

    def test_frozen_original_corpus(self) -> None:
        """All original behavioral inputs retain decisions, identifiers, and safe routes."""
        cases: list[dict[str, Any]] = sorted(
            [row for path in FIXTURES.glob("*.json") for row in json.loads(path.read_text())],
            key=lambda row: row["fixture_index"],
        )
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            for name in ("main_repo", "feat_repo", "allowlist_repo", "no_allowlist_repo", "no_intra_repo", "opt_repo"):
                path = sandbox / name
                subprocess.run(["git", "init", "-q", str(path)], check=True)
                branch = "main" if name == "main_repo" else "feat/test"
                subprocess.run(["git", "-C", str(path), "checkout", "-b", branch, "-q"], check=True)
            for index, raw in enumerate(cases):
                case = json.loads(json.dumps(raw).replace("{sandbox}", directory))
                request = case["request"]
                cwd = Path(request.get("cwd", case.get("execution_cwd", directory)))
                allowlist = cwd / ".claude/destructive_allowlist"
                allowlist.parent.mkdir(parents=True, exist_ok=True)
                if case["allowlist"] is None:
                    allowlist.unlink(missing_ok=True)
                else:
                    allowlist.write_text(case["allowlist"])
                with self.subTest(source=case["source"], index=index, command=request.get("tool_input")):
                    result = subprocess.run(
                        [sys.executable, str(HOOK)],
                        input=json.dumps(request),
                        capture_output=True,
                        text=True,
                        cwd=case.get("execution_cwd", str(sandbox)),
                        env={**os.environ, "CLAUDE_DISCIPLINE_LOG": str(sandbox / "discipline.log")},
                        check=False,
                    )
                    self.assertEqual(result.returncode, case["returncode"], result.stderr)
                    actual: dict[str, Any] = (
                        json.loads(result.stdout).get("hookSpecificOutput", {}) if result.stdout.strip() else {}
                    )
                    expected: dict[str, Any] = case["expected"].get("hookSpecificOutput", {})
                    self.assertEqual(actual.get("permissionDecision"), expected.get("permissionDecision"))
                    self.assertEqual(actual.get("patternId"), expected.get("patternId"))
                    if actual.get("patternId"):
                        self.assertEqual(actual["permissionDecisionReason"], expected["permissionDecisionReason"])
            self.assertEqual(len(cases), 391)

    def test_python_workflow_substitution(self) -> None:
        """The migrated workflow names retain the same process-substitution gate."""
        for script in ("push", "merge", "post_review", "post_evals"):
            request = {"tool_input": {"command": f'python3 scripts/{script}.py "note" <(touch marker)'}}
            result = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(request), capture_output=True, text=True, check=False
            )
            self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_routes_are_specific_and_identifiers_are_mention_safe(self) -> None:
        """Every route has a safe identifier and names a concrete alternative."""
        for identifier, route in ROUTES.items():
            self.assertRegex(identifier, r"^[a-z]+(?:-[a-z0-9]+)+$")
            self.assertIn("Safe route:", route)
            request = {"tool_input": {"command": f"echo {identifier}"}}
            result = subprocess.run(
                [sys.executable, str(HOOK)], input=json.dumps(request), capture_output=True, text=True, check=False
            )
            self.assertEqual(result.stdout, "")


class AuthorityDeniedLeaseTests(unittest.TestCase):
    """A live authority that denies destructive_shell also refuses the allowlisted --force-with-lease family."""

    LEASE = "git push --force-with-lease origin feat/x"

    def setUp(self) -> None:
        """A feature-branch repo that opts in to force-with-lease, and a private loop dir."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = Path(temporary.name)
        self.repo = self.tmp / "repo"
        subprocess.run(["git", "init", "-q", "-b", "feat/x", str(self.repo)], check=True)
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude/destructive_allowlist").write_text("git-push-force-with-lease\n")
        self.loop = self.tmp / "loops"

    def grant(self, denied: list[str]) -> None:
        """Write a live authority for session s1."""
        obj = {
            "authority_id": "auth-1", "loop_id": None, "session_id": "s1", "scope": ["code"], "denied": denied,
            "max_prs": 1, "expires_at": "2999-01-01T00:00:00+00:00", "revocable": True,
            "approval_required_for": ["merge"], "granted_by": "command",
        }  # fmt: skip
        path = self.loop / "s1" / "authority.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj))

    def run_hook(self, command: str) -> dict[str, Any]:
        """The hook's hookSpecificOutput for one command ({} when it stands aside)."""
        payload = {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": command}}
        env = os.environ | {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop), "CLAUDE_DISCIPLINE_LOG": str(self.tmp / "d.log")}
        done = subprocess.run(
            [sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env,
            check=False,
        )  # fmt: skip
        return dict(json.loads(done.stdout)["hookSpecificOutput"]) if done.stdout.strip() else {}

    def test_lease_is_allowed_unless_the_authority_denies_destructive_shell(self) -> None:
        """No authority and an authority without the category allow it; with the category it is denied and traced."""
        self.assertEqual(self.run_hook(self.LEASE), {})
        self.grant(denied=["merge"])
        self.assertEqual(self.run_hook(self.LEASE), {})
        self.grant(denied=["destructive_shell"])
        out = self.run_hook(self.LEASE)
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("authority_denied_destructive_shell", out["permissionDecisionReason"])
        rows = (self.loop / "s1" / "trace.jsonl").read_text()
        self.assertIn("authority_denied_destructive_shell", rows)

    def test_permanent_blocklist_is_unchanged_and_unrelated_commands_untouched(self) -> None:
        """The rm -rf pattern is blocked by id either way; an ordinary command stays allowed."""
        self.grant(denied=["destructive_shell"])
        self.assertEqual(self.run_hook("rm -rf build")["patternId"], "rm-rf")
        self.assertEqual(self.run_hook("ls -la"), {})

    def test_calls_permits_for_destructive_shell(self) -> None:
        """Spy: main() asks permits(session, 'destructive_shell') for the lease family only."""
        from unittest import mock

        from hooks.scripts import destructive_bash_gate as hook

        allow = {"allow": True, "reason": "ok", "requires_approval": False, "authority_id": None}
        for command, calls in ((self.LEASE, 1), ("ls -la", 0)):
            payload = {"session_id": "s1", "cwd": str(self.repo), "tool_input": {"command": command}}
            with (
                mock.patch.object(hook, "read_payload", return_value=payload),
                mock.patch.object(hook, "permits", return_value=allow) as spy,
            ):
                hook.main()
            self.assertEqual(spy.call_count, calls)
            if calls:
                self.assertEqual(spy.call_args.args, ("s1", "destructive_shell"))


if __name__ == "__main__":
    unittest.main()
