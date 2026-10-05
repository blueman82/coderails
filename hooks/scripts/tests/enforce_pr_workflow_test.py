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
from hooks.scripts.lib import pr_workflow_match
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
            # fixed dates make every fixture repo's init commit the same sha, so the PR head exists in each one;
            # origin/main at that commit gives the publication gate a computable (empty) diff and no network fetch
            date = "2026-01-01T00:00:00Z"
            fixed = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
            for command in (
                ("config", "user.email", "t@t.t"),
                ("config", "user.name", "t"),
                ("remote", "add", "origin", "https://github.com/acme/widgets.git"),
                ("commit", "-q", "--allow-empty", "-m", "init"),
                ("update-ref", "refs/remotes/origin/main", "HEAD"),
            ):
                subprocess.run(["git", "-C", str(repo), *command], check=True, env=fixed)
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
                wrapped_merge = case["request"]["tool_input"]["command"] in (
                    "command bash scripts/merge.sh 140",
                    "command python3 scripts/merge.py 140",
                )
                self.assertEqual(
                    '"deny"' in result.stdout, case["denied"] or wrapped_merge, result.stdout + result.stderr
                )
                if wrapped_merge:
                    self.assertIn("requires /pr-review-toolkit:review-pr", result.stdout)
        self.assertEqual(original_count, 114)

    def test_global_option_and_path_forms_are_guarded(self) -> None:
        """Git -C/-c/--no-pager and absolute-path forms of push-to-main and merge are seen as the plain form is."""
        main = self.git_repo("on_main", "main")
        feature = self.git_repo("on_feature", "feature/x")
        merge = f"git -C {main} merge x"
        self.assertEqual(pr_workflow_match.operation(merge), ("git_merge", merge, str(main)))
        self.assertEqual(pr_workflow_match.operation("git -c a=b merge x")[0], "git_merge")
        self.assertEqual(pr_workflow_match.operation('echo "git -c a=b merge x"')[0], "")
        guarded = {
            "git -C {main} push origin main": "git_push",
            "git -c user.name=x push origin main": "git_push",
            "git --no-pager push origin main": "git_push",
            "/usr/bin/git push origin main": "git_push",
            "env A=1 git -C {main} push": "git_push",
            "bash -c 'git -c a=b push origin main'": "git_push",
        }
        for template, name in guarded.items():
            command = template.format(main=main)
            with self.subTest(command=command):
                found = pr_workflow_match.guarded_segments(command, str(feature))
                self.assertEqual([entry[0] for entry in found], [name])
        quiet = ('echo "git -c a=b push origin main"', "git -c a=b push origin feature/x", "git log --grep push")
        for command in quiet:
            with self.subTest(command=command):
                self.assertEqual(pr_workflow_match.guarded_segments(command, str(feature)), [])


if __name__ == "__main__":
    unittest.main()
