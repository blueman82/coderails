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

    def test_no_verify_is_seen_behind_global_options_and_wrappers(self) -> None:
        """Git -C/-c commit --no-verify and -n are denied with the established identifier; quoted text is not."""
        denied = ("git -C d commit --no-verify", "git commit -n", "git -c a=b commit -nm x", "env A=1 git commit -n")
        allowed = (
            "git commit -m x",
            "git -C d commit -m x",
            'echo "git commit -n"',
            "git commit -m -n",
            'echo "git commit -m x --no-verify"',
            'git commit -m "text --no-verify"',
        )
        for command, expected in [(c, True) for c in denied] + [(c, False) for c in allowed]:
            with self.subTest(command=command):
                result = subprocess.run(
                    [sys.executable, str(HOOK)],
                    input=json.dumps({"tool_input": {"command": command}}),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                decoded: dict[str, Any] = json.loads(result.stdout) if result.stdout.strip() else {}
                output: dict[str, Any] = decoded.get("hookSpecificOutput", {})
                self.assertEqual(output.get("patternId") == "git-commit-no-verify", expected)

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


if __name__ == "__main__":
    unittest.main()
