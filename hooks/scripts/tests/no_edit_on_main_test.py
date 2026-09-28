"""Verify file-repository branch ownership, plugin Markdown, and owner settings gates."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase


class MainEditTests(HookCase):
    """The target file's repository owns edit policy, independently of session cwd."""

    def setUp(self) -> None:
        """Create plugin, non-plugin, and unrelated feature repositories."""
        super().setUp()
        self.repo = self.repository("plugin", "main")
        self.wiki = self.repository("wiki", "main")
        self.other = self.repository("other", "feature")
        marker = self.repo / ".claude-plugin/plugin.json"
        marker.parent.mkdir()
        marker.write_text('{"name":"test"}', encoding="utf-8")

    def decision(self, file: str | Path, cwd: Path | None = None, tool: str = "Edit") -> bool:
        """Apply a native file-edit request to the current fixture repositories."""
        return self.denied(
            "no_edit_on_main", {"tool_name": tool, "cwd": str(cwd or self.repo), "tool_input": {"file_path": str(file)}}
        )

    def test_branches_and_allowlist(self) -> None:
        """Protect code on both default branches and preserve document/config exceptions."""
        blocked = [
            f"src/file.{extension}" for extension in ("py", "ts", "tsx", "js", "jsx", "go", "rs", "java", "sh", "sql")
        ]
        blocked += ["deploy.gitignore", "skills/agentic-loop/SKILL.md", "commands/push.md"]
        for branch in ("main", "master"):
            self.branch(self.repo, branch)
            for file in blocked:
                self.assertTrue(self.decision(file, tool="MultiEdit"), file)
            for file in (
                "README.md",
                "docs/REFERENCE.md",
                "skills/foo/references/x.md",
                "config.json",
                "config.yaml",
                ".github/ci.yml",
                "Cargo.toml",
                "setup.ini",
                "myapp.cfg",
                "notes.txt",
                "docs/guide.rst",
                ".gitignore",
                "src/.gitignore",
                "LICENSE",
                "",
            ):
                self.assertFalse(self.decision(file, tool="Write"), file)
        self.branch(self.repo, "feature")
        for file in blocked:
            self.assertFalse(self.decision(file), file)

    def test_file_repo_and_plugin_marker(self) -> None:
        """Non-plugin Markdown survives, but any main-branch code remains protected."""
        for file in ("commands/init.md", "skills/foo/SKILL.md"):
            self.assertFalse(self.decision(self.wiki / file))
        self.assertTrue(self.decision(self.wiki / "src/app.py"))
        self.assertTrue(self.decision(self.repo / "commands/push.md", cwd=self.other))
        self.assertTrue(self.decision(self.repo / "skills/foo/SKILL.md"))
        self.assertFalse(self.decision(self.directory / "loose/dir/app.py"))

    def test_owner_permission_files(self) -> None:
        """Owner settings are denied before branch and suffix exemptions."""
        for branch in ("main", "feature"):
            self.branch(self.repo, branch)
            for file in (
                ".claude/settings.json",
                "./.claude/settings.json",
                ".claude/settings.local.json",
                str(self.repo / ".claude/settings.json"),
                str(self.wiki / ".claude/settings.json"),
            ):
                self.assertTrue(self.decision(file), file)
        for file in ("app/settings.json", ".claude/sub/settings.json", ".claude/sub/settings.local.json"):
            self.assertFalse(self.decision(file), file)


if __name__ == "__main__":
    unittest.main()
