#!/usr/bin/env python3
"""Preserve the original PR workflow corpus at the real Python/Git/GitHub process seam."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HOOKS, HookTestCase

FIXTURES = Path(__file__).with_name("fixtures")


class WorkflowGateTests(HookTestCase):
    """Replay original registration, review ordering, branches, and exact-head eval gates."""

    def test_original_corpus(self) -> None:
        """Every original hook input retains allow/deny behavior after native migration."""
        cases: list[dict[str, Any]] = sorted(
            [row for path in (FIXTURES / "pr_workflow_cases").glob("*.json") for row in json.loads(path.read_text())],
            key=lambda row: row["fixture_index"],
        )
        python_cases = [
            json.loads(
                json.dumps(case)
                .replace("merge.sh", "merge.py")
                .replace("push.sh", "push.py")
                .replace("bash ", "python3 ")
            )
            for case in cases
            if "merge.sh" in json.dumps(case) or "push.sh" in json.dumps(case)
        ]
        self.assertGreater(len(python_cases), 10)
        original_count = len(cases)
        cases.extend(python_cases)
        repositories = {path: branch for case in cases for path, branch in case["repositories"].items()}
        for raw, branch in repositories.items():
            name = raw.replace("{sandbox}/", "")
            repo = self.git_repo(name, branch)
            for command in (
                ("config", "user.email", "t@t.t"),
                ("config", "user.name", "t"),
                ("remote", "add", "origin", "https://github.com/acme/widgets.git"),
                ("commit", "-q", "--allow-empty", "-m", "init"),
            ):
                subprocess.run(["git", "-C", str(repo), *command], check=True)
        fixture_sha = subprocess.check_output(
            ["git", "-C", str(self.directory / "repo"), "rev-parse", "HEAD"], text=True
        ).strip()
        mock = self.directory / "mockbin"
        mock.mkdir()
        shutil.copyfile(FIXTURES / "pr_gh.py", mock / "gh")
        (mock / "gh").chmod(0o755)
        environment = {
            **self.environment,
            "PATH": str(mock) + os.pathsep + os.environ["PATH"],
            "FIXTURE_HEAD_SHA": fixture_sha,
        }
        previous: set[Path] = set()
        for index, original in enumerate(cases):
            case = json.loads(
                json.dumps(original).replace("{sandbox}", str(self.directory)).replace("{head_sha}", fixture_sha)
            )
            for path in previous:
                path.unlink(missing_ok=True)
            previous = set()
            for name, contents in case["files"].items():
                path = Path(name)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(contents)
                previous.add(path)
            with self.subTest(index=index, command=case["request"]["tool_input"]["command"]):
                result = subprocess.run(
                    [sys.executable, str(HOOKS / "enforce_pr_workflow.py")],
                    input=json.dumps(case["request"]),
                    text=True,
                    capture_output=True,
                    env={**environment, **case["env"]},
                    check=False,
                )
                self.assertEqual(result.returncode, case["returncode"], result.stderr)
                self.assertEqual('"deny"' in result.stdout, case["denied"], result.stdout + result.stderr)
        self.assertEqual(original_count, 114)


if __name__ == "__main__":
    unittest.main()
