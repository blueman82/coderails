"""Check filesystem isolation, review grammar, staging and merge refusal contracts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts import merge, post_review, push
from scripts.lib import config, git_common


class WorkflowCliTests(unittest.TestCase):
    """Pin migration behavior without contacting a remote or committing source."""

    def test_config_nearest_and_symlink_floor(self) -> None:
        """Resolve nearest configuration without walking past the Git root."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repository"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            nested = root / "apps/web"
            nested.mkdir(parents=True)
            link = Path(temporary) / "linked"
            link.symlink_to(root, target_is_directory=True)
            self.assertEqual(config.config_path(link / "apps/web"), "")
            for directory in (root, root / "apps"):
                (directory / ".coderails").mkdir()
                (directory / ".coderails/workflow.config.yaml").write_text("wiki_path: null\n")
            self.assertEqual(config.config_path(nested), str((root / "apps/.coderails/workflow.config.yaml").resolve()))
            self.assertEqual(config.config_path(Path(temporary)), "")

    def test_review_sections_and_cache(self) -> None:
        """Reject empty or ambiguous summaries; preserve unrelated cache state."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "summary.md"
            for text in ("## No findings\n", "## Critical\nNone\n## Important\n- a\n## Suggestions\nNone\n"):
                path.write_text(text)
                post_review.validate_summary(path)
            for text in ("## No findings\n## Critical\n", "## Critical\n## Important\nNone\n## Suggestions\nNone\n"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    post_review.validate_summary(path)
            progress = Path(temporary) / "progress.json"
            progress.write_text('{"preserve":true}')
            self.assertEqual(post_review.write_cache(progress, "7", "sha", "url", "owner", "today"), 0)
            data = json.loads(progress.read_text())
            self.assertTrue(data["preserve"])
            self.assertEqual(data["review"]["head_sha"], "sha")

    def test_staging_excludes_untracked_without_explicit_path(self) -> None:
        """Stage only tracked updates and named new files."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "tracked").write_text("before")
            subprocess.run(["git", "-C", temporary, "add", "tracked"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    temporary,
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.test",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                check=True,
            )
            (root / "tracked").write_text("after")
            (root / "included").write_text("selected")
            (root / "unrelated").write_text("keep")
            original = git_common.run

            def run(*arguments: str, check: bool = False) -> subprocess.CompletedProcess[str]:
                """Route Git operations to the fixture and observe the commit boundary."""
                if arguments[:2] == ("git", "commit"):
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                return original("git", "-C", temporary, *arguments[1:], check=check)

            with patch.object(git_common, "run", side_effect=run):
                push.commit("change", "", ["included"])
            staged = subprocess.check_output(["git", "-C", temporary, "diff", "--cached", "--name-only"], text=True)
            self.assertEqual(set(staged.splitlines()), {"tracked", "included"})

    def test_missing_review_stops_before_remote_merge(self) -> None:
        """A failed evidence gate cannot reach gh pr merge."""
        with (
            patch.object(git_common, "pr_field", return_value="sha"),
            patch.object(git_common, "gate_review_summary_for_pr", return_value=(1, "")),
            self.assertRaises(git_common.WorkflowError),
        ):
            merge.verify_gates("1")


if __name__ == "__main__":
    unittest.main()
