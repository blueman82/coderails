#!/usr/bin/env python3
"""Check headless child commands against the outer publication gate."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts import enforce_pr_workflow
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


class HeadlessBoundaryTests(HookTestCase):
    """A child action must keep the outer repository and session boundary."""

    def test_headless_agent_cli_values_do_not_hide_merge_prompt(self) -> None:
        """CLI options with values leave the child prompt available to the merge gate."""
        from hooks.scripts.lib.pr_workflow_match import guarded_segments

        commands = (
            "codex -m gpt-5 exec 'gh pr merge 42'",
            "codex e 'gh pr merge 42'",
            "codex --enable search exec --add-dir /tmp --output-schema /tmp/schema.json 'gh pr merge 42'",
            "codex exec --thread-source cli --disable feature --output-last-message /tmp/out 'gh pr merge 42'",
            "codex exec --local-provider ollama 'gh pr merge 42'",
            "claude --bare -p --agent general-purpose 'gh pr merge 42'",
            "claude -p --fallback-model sonnet --effort high 'gh pr merge 42'",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(
                    guarded_segments(command, str(self.directory)), [("merge", "gh pr merge 42", str(self.directory))]
                )

        for command in (
            "codex exec --output-schema 'gh pr merge 42' 'explain the code'",
            "claude -p --agent 'gh pr merge 42' 'explain the code'",
        ):
            with self.subTest(inert=command):
                self.assertEqual(guarded_segments(command, str(self.directory)), [])

    def test_compound_merges_are_refused_before_publication(self) -> None:
        """A second PR in one shell call cannot use the first PR's evidence."""
        payload = {
            "cwd": str(self.directory),
            "session_id": "test",
            "tool_input": {"command": "gh pr merge 42 && gh pr merge 43"},
        }
        with (
            patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
            patch("hooks.scripts.enforce_pr_workflow.publication_gate.enforce") as publication,
            patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
        ):
            enforce_pr_workflow.main()
        publication.assert_not_called()
        self.assertIn("one protected action", deny.call_args.args[0])

    def test_merge_and_protected_push_are_refused_as_one_call(self) -> None:
        """The hook cannot apply one operation's evidence to a later protected push."""
        payload = {
            "cwd": str(self.directory),
            "session_id": "test",
            "tool_input": {"command": "gh pr merge 42 && git push origin HEAD:main"},
        }
        with (
            patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
            patch("hooks.scripts.enforce_pr_workflow.publication_gate.enforce") as publication,
            patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
        ):
            enforce_pr_workflow.main()
        publication.assert_not_called()
        self.assertIn("one protected action", deny.call_args.args[0])

    def test_push_option_value_does_not_hide_protected_push(self) -> None:
        """Git accepts --help as a push-option value, so the push remains guarded."""
        from hooks.scripts.lib.pr_workflow_match import operation

        for prefix in ("git", "git -C /tmp", "git -c foo=bar", "git --git-dir .git", "git --work-tree ."):
            for option in ("-o --help", "--push-option=--help"):
                command = f"{prefix} push {option} origin HEAD:main"
                with self.subTest(command=command):
                    expected_dir = "/tmp" if prefix == "git -C /tmp" else ""
                    self.assertEqual(operation(command), ("git_push", command, expected_dir))

    def test_headless_child_cwd_override_is_unbindable(self) -> None:
        """A child may select another repository, so local PR evidence cannot authorize it."""
        from hooks.scripts.lib.pr_workflow_match import UNBINDABLE, guarded_segments

        for command in (
            "codex -C /tmp exec 'gh pr merge 42'",
            "codex exec -C /tmp 'gh pr merge 42'",
            "codex --cd=/tmp exec 'gh pr merge 42'",
            "codex -C /tmp e 'gh pr merge 42'",
            "codex -C/tmp exec 'gh pr merge 42'",
            "claude --cd /tmp -p 'gh pr merge 42'",
        ):
            with self.subTest(command=command):
                found = guarded_segments(command, str(self.directory))
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0][0], "merge")
                self.assertTrue(found[0][1].startswith(UNBINDABLE))

    def test_headless_child_cwd_override_is_denied_before_publication(self) -> None:
        """The outer hook refuses a child merge in a different working directory."""
        payload = {
            "cwd": str(self.directory),
            "session_id": "test",
            "tool_input": {"command": "codex -C /tmp exec 'gh pr merge 42'"},
        }
        with (
            patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
            patch("hooks.scripts.enforce_pr_workflow.publication_gate.enforce") as publication,
            patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
        ):
            enforce_pr_workflow.main()
        publication.assert_not_called()
        self.assertIn("working directory", deny.call_args.args[0])

    def test_headless_protected_push_reaches_outer_hook(self) -> None:
        """A child push reaches the same session gate as a direct push."""
        from hooks.scripts.lib.pr_workflow_match import guarded_segments

        for command in (
            "claude -p 'git push origin HEAD:main'",
            "codex -C /tmp exec 'git push origin HEAD:main'",
        ):
            with self.subTest(command=command):
                payload = {"cwd": str(self.directory), "session_id": "test", "tool_input": {"command": command}}
                with (
                    patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
                    patch("hooks.scripts.enforce_pr_workflow.config_path", return_value="config"),
                    patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
                ):
                    enforce_pr_workflow.main()
                self.assertTrue(guarded_segments(command, str(self.directory)))
                self.assertTrue(deny.called)

    def test_git_global_cwd_override_is_denied_before_parent_repo_checks(self) -> None:
        """A Git -C push may target another repository with different policy."""
        for command in (
            "git -C /tmp push -o --help origin HEAD:main",
            "claude -p 'git -C /tmp push -o --help origin HEAD:main'",
            "git --git-dir=.git push -o --help origin HEAD:main",
            "codex exec 'git --work-tree /tmp push -o --help origin HEAD:main'",
            "git -C '/tmp/repo with space' push origin HEAD:main",
            "claude -p \"git -C '/tmp/repo with space' push origin HEAD:main\"",
        ):
            with self.subTest(command=command):
                payload = {"cwd": str(self.directory), "session_id": "test", "tool_input": {"command": command}}
                with (
                    patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
                    patch("hooks.scripts.enforce_pr_workflow.config_path") as config,
                    patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
                ):
                    enforce_pr_workflow.main()
                config.assert_not_called()
                self.assertIn("working directory", deny.call_args.args[0])

    def test_plain_protected_push_and_feature_push_keep_their_boundary(self) -> None:
        """A direct main push needs session evidence; a feature push stays outside that gate."""
        for command, blocked in (
            ("git push origin HEAD:main", True),
            ("git push -o --help origin HEAD:main", True),
            ("git push origin HEAD:feature", False),
        ):
            with self.subTest(command=command):
                payload = {"cwd": str(self.directory), "session_id": "test", "tool_input": {"command": command}}
                with (
                    patch("hooks.scripts.enforce_pr_workflow.read_payload_strict", return_value=payload),
                    patch("hooks.scripts.enforce_pr_workflow.config_path", return_value="config"),
                    patch("hooks.scripts.enforce_pr_workflow.deny") as deny,
                ):
                    enforce_pr_workflow.main()
                self.assertEqual(deny.called, blocked)


if __name__ == "__main__":
    unittest.main()
