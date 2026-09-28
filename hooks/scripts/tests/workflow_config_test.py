"""Preserve configuration discovery and machine-local ignore contracts."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.lib.config import config_path, config_value, resolve_config

REPOSITORY = Path(__file__).resolve().parents[3]


class WorkflowConfigTests(unittest.TestCase):
    """Find only canonical configuration, bounded by the repository root."""

    def test_root_nested_symlink_and_missing(self) -> None:
        """Cover both canonical and symlinked roots and nearest-wins lookup."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "repo"
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            link = root.with_name("link")
            link.symlink_to(root, target_is_directory=True)
            self.assertEqual(config_path(link), "")
            self.assertEqual(resolve_config(link), "NO_CONFIG\n")
            for legacy in (".claude", ".codex"):
                (root / legacy).mkdir()
                (root / legacy / "workflow.config.yaml").write_text("legacy: true\n")
            self.assertEqual(config_path(root), "")
            config = root / ".coderails/workflow.config.yaml"
            config.parent.mkdir()
            config.write_text("wiki_path: null\n")
            self.assertEqual(config_path(link), str(config))
            self.assertEqual(config_path(root), str(config))
            self.assertEqual(resolve_config(root), "wiki_path: null\n")
            nested = root / "apps/web"
            nested.mkdir(parents=True)
            self.assertEqual(config_path(nested), str(config))
            nearer = root / "apps/.coderails/workflow.config.yaml"
            nearer.parent.mkdir()
            nearer.write_text("wiki_path: other\n")
            self.assertEqual(config_path(nested), str(nearer))
            self.assertEqual(config_path(root.parent), "")

    def test_runtime_and_scratch_ignored(self) -> None:
        """Keep all canonical local state out of Git at root and nested scopes."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            shutil.copyfile(REPOSITORY / ".gitignore", root / ".gitignore")
            for prefix in ("", "nested/"):
                for relative in (".coderails/progress.json", ".coderails/workflow.config.yaml", ".tmp/scratch"):
                    path = root / (prefix + relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
                    result = subprocess.run(
                        ["git", "-C", temporary, "check-ignore", "-q", prefix + relative], check=False
                    )
                    self.assertEqual(result.returncode, 0, prefix + relative)

    def test_scalar_quotes_comments_and_sections(self) -> None:
        """Limit attestor parsing to its own section and strip scalar comments."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            path.write_text(
                'wiki_path: "../wiki" # path\nintegrity_review:\n'
                '  machine_user: "attestor" # owner\nnext:\n  machine_user: wrong\n'
            )
            self.assertEqual(config_value(path, "wiki_path"), "../wiki")
            self.assertEqual(config_value(path, "machine_user", "integrity_review"), "attestor")


if __name__ == "__main__":
    unittest.main()
