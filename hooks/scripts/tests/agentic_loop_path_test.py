#!/usr/bin/env python3
"""Test canonical state paths, session isolation, worktree stability, and probing."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.lib.agentic_loop_path import resolve_path, sanitise_session_id
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


class AgenticLoopPathTests(HookTestCase):
    """Preserve the sole state resolver without migrating or writing state."""

    def test_defaults_sessions_and_sanitization(self) -> None:
        """Session overrides remain stable; missing and malformed IDs remain isolated."""
        with patch.dict(os.environ, self.environment):
            self.assertEqual(
                resolve_path("/Users/foo/bar", "S1"), self.directory / "state/-Users-foo-bar/S1/progress.json"
            )
            self.assertNotEqual(resolve_path("/x", "S1"), resolve_path("/x", "S2"))
            self.assertEqual(resolve_path("/x", "S1"), resolve_path("/x", "S1"))
            with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": "S_ENV"}):
                self.assertEqual(resolve_path("/x").parent.name, "S_ENV")
            with patch.dict(os.environ, {"CLAUDE_CODE_SESSION_ID": ""}):
                self.assertNotEqual(resolve_path("/x"), resolve_path("/x"))
            for raw, expected in (("S1/evil", "S1_evil"), ("../../S1", "__S1"), ("x[1]", "x[1]")):
                self.assertEqual(sanitise_session_id(raw), expected)
            self.assertFalse((self.directory / "state").exists())

    def test_real_worktree_and_independent_repository_identity(self) -> None:
        """A real Git worktree shares state identity while independent repositories differ."""
        primary = self.git_repo("primary")
        subprocess.run(
            [
                "git",
                "-C",
                str(primary),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "--allow-empty",
                "-m",
                "fixture",
                "-q",
            ],
            check=True,
        )
        worktree = self.directory / "worktree"
        subprocess.run(["git", "-C", str(primary), "worktree", "add", "-q", "-b", "worker", str(worktree)], check=True)
        independent = self.git_repo("independent")
        with patch.dict(os.environ, self.environment):
            self.assertEqual(resolve_path(str(primary), "S1"), resolve_path(str(worktree), "S1"))
            self.assertNotEqual(resolve_path(str(primary), "S1"), resolve_path(str(independent), "S1"))

    def test_existing_session_probe_and_canonical_precedence(self) -> None:
        """Existing state survives slug drift; canonical state wins deterministic probes."""
        with patch.dict(os.environ, self.environment):
            canonical = resolve_path("/new", "S1")
            alternate = self.directory / "state/old/S1/progress.json"
            alternate.parent.mkdir(parents=True)
            alternate.write_text("{}")
            self.assertEqual(resolve_path("/new", "S1"), alternate)
            alias = self.directory / "state/alias"
            alias.symlink_to(alternate.parents[1], target_is_directory=True)
            self.assertEqual(resolve_path("/new", "S1"), alias / "S1/progress.json")
            canonical.parent.mkdir(parents=True)
            canonical.write_text("{}")
            self.assertEqual(resolve_path("/new", "S1"), canonical)

    def test_git_failures_and_nonabsolute_output(self) -> None:
        """Missing Git, command failures, and old-Git garbage all retain cwd fallback."""
        cwd = str(self.directory / "has spaces/dir")
        with patch.dict(os.environ, self.environment):
            expected = self.directory / "state" / cwd.replace("/", "-") / "S1/progress.json"
            for result in (
                subprocess.CompletedProcess([], 1, "", ""),
                subprocess.CompletedProcess([], 0, "--path-format=absolute .git\n", ""),
                subprocess.CompletedProcess([], 0, "", ""),
            ):
                with patch("hooks.scripts.lib.agentic_loop_path.subprocess.run", return_value=result):
                    self.assertEqual(resolve_path(cwd, "S1"), expected)
            with patch("hooks.scripts.lib.agentic_loop_path.subprocess.run", side_effect=FileNotFoundError):
                self.assertEqual(resolve_path(cwd, "S1"), expected)


if __name__ == "__main__":
    unittest.main()
