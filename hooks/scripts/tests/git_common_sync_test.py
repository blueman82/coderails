"""Verify post-merge Git synchronization using local bare repositories only."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.run_all import isolated_environment
from scripts.lib import git_common


def git(directory: Path, *arguments: str) -> str:
    """Run an isolated fixture Git command with no user hooks or network remotes."""
    environment = dict(isolated_environment(), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    result = subprocess.run(
        ["git", "-c", f"core.hooksPath={os.devnull}", "-C", str(directory), *arguments],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class GitSyncTests(unittest.TestCase):
    """Drive the production sync helper against real fixture commits and worktrees."""

    def test_linked_primary_and_space_paths(self) -> None:
        """Fast-forward the primary tree from a linked worker and later its own feature."""
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            origin, primary, worker, scratch = (
                base / name for name in ("origin.git", "primary with space", "worker", "scratch")
            )
            git(base, "init", "--bare", str(origin))
            git(base, "init", str(primary))
            git(primary, "config", "user.name", "Fixture")
            git(primary, "config", "user.email", "fixture@example.invalid")
            git(primary, "checkout", "-b", "main")
            (primary / "file").write_text("initial")
            git(primary, "add", "file")
            git(primary, "commit", "-m", "fixture initial")
            git(primary, "remote", "add", "origin", str(origin))
            git(primary, "push", "-u", "origin", "main")
            git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
            git(primary, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
            git(primary, "worktree", "add", "-b", "worker", str(worker))
            git(base, "clone", str(origin), str(scratch))
            git(scratch, "config", "user.name", "Fixture")
            git(scratch, "config", "user.email", "fixture@example.invalid")
            for index, location in enumerate((worker, primary)):
                if location == primary:
                    git(primary, "checkout", "-b", "primary-feature")
                (scratch / "file").write_text(f"merged {index}")
                git(scratch, "commit", "-am", "fixture merged")
                git(scratch, "push", "origin", "main")
                expected = git(scratch, "rev-parse", "HEAD")

                def invoke(
                    *arguments: str, check: bool = False, fixture_location: Path = location
                ) -> subprocess.CompletedProcess[str]:
                    """Bind production commands to the fixture worker's checkout."""
                    command = [arguments[0], "-c", f"core.hooksPath={os.devnull}", *arguments[1:]]
                    return subprocess.run(
                        command,
                        cwd=fixture_location,
                        env=dict(isolated_environment(), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"),
                        capture_output=True,
                        text=True,
                        check=check,
                    )

                with patch.object(git_common, "run", side_effect=invoke):
                    git_common.sync_main_branch()
                self.assertEqual(git(primary, "rev-parse", "HEAD"), expected)
                self.assertEqual(git(primary, "branch", "--show-current"), "main")

    def test_fallback_repo_names_and_nonfatal_sync(self) -> None:
        """Fallback main, dotted GitHub slugs and failed sync retain their contracts."""
        with patch.object(git_common, "run", return_value=subprocess.CompletedProcess([], 1, "", "failed")):
            self.assertEqual(git_common.main(), "main")
            git_common.sync_main_branch()
            self.assertEqual(git_common.pr_field("1", "headRefOid"), "")
        with patch.object(git_common, "run", side_effect=FileNotFoundError("git unavailable")):
            git_common.sync_main_branch()
        for url in ("git@github.com:owner/repo.with.dots.git", "https://github.com/owner/repo.with.dots.git"):
            self.assertEqual(git_common.repo_from_url(url), "owner/repo.with.dots")


if __name__ == "__main__":
    unittest.main()
