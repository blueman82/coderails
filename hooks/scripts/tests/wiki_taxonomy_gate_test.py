#!/usr/bin/env python3
"""Preserve live taxonomy, vault identity, path resolution, and fail-open behavior."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.lib.hook_test_support import HookTestCase


class WikiTaxonomyTests(HookTestCase):
    """Block unsanctioned types only after positively identifying a configured vault."""

    def setUp(self) -> None:
        """Create independent plugin and wiki Git repositories."""
        super().setUp()
        self.plugin = self.git_repo("plugin")
        self.vault = self.git_repo("vault")
        self.schema = self.plugin / "AGENTS.md"
        self.schema.write_text("## Page types\n| `investigations/` | pages |\n| `concepts/` | pages |\n")
        (self.vault / "investigations").mkdir()
        (self.vault / "concepts").mkdir()
        (self.plugin / ".coderails").mkdir()
        self.config = self.plugin / ".coderails/workflow.config.yaml"
        self.config.write_text(f"wiki_path: {self.vault}\n")

    def decision(self, file: Path) -> dict[str, object]:
        """Evaluate one target path using the live plugin schema and configuration."""
        result = self.run_hook(
            "wiki_taxonomy_gate",
            {"cwd": str(self.vault), "tool_input": {"file_path": str(file)}},
            CLAUDE_PLUGIN_ROOT=str(self.plugin),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout).get("hookSpecificOutput", {}) if result.stdout else {}

    def test_sanctioned_and_exempt_paths(self) -> None:
        """Sanctioned types, raw data, root metadata, and exempt dot directories pass."""
        for name in (
            "investigations/a.md",
            "concepts/a.md",
            "raw/a.txt",
            "index.md",
            ".obsidian/a",
            ".git/a",
            ".claude/a",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.decision(self.vault / name), {})
        denial = self.decision(self.vault / "decisions/a.md")
        self.assertEqual(denial["permissionDecision"], "deny")
        for text in ("decisions/", "investigations/", str(self.schema)):
            self.assertIn(text, str(denial["permissionDecisionReason"]))

    def test_dynamic_taxonomy(self) -> None:
        """Adding one page type changes the decision without editing the hook."""
        target = self.vault / "newtype/a.md"
        self.assertEqual(self.decision(target)["permissionDecision"], "deny")
        self.schema.write_text(self.schema.read_text() + "| `newtype/` | new |\n")
        self.assertEqual(self.decision(target), {})

    def test_ambiguous_schema_and_identity_fail_open(self) -> None:
        """Missing metadata or an unrelated Git root cannot activate vault policing."""
        self.assertEqual(self.decision(self.plugin / "hooks/new.py"), {})
        for source in ("# no schema", "## Page types\nno parseable paths\n", "## Other\n`investigations/`\n"):
            self.schema.write_text(source)
            self.assertEqual(self.decision(self.vault / "decisions/a.md"), {})
        self.schema.unlink()
        self.assertEqual(self.decision(self.vault / "decisions/a.md"), {})

    def test_configuration_and_directory_threshold(self) -> None:
        """Missing, null, unresolved, or mismatching vault paths and sparse dirs pass."""
        target = self.vault / "decisions/a.md"
        for config in ("", "wiki_path: null", "wiki_path: ~", "wiki_path: missing", f"wiki_path: {self.plugin}"):
            self.config.write_text(config)
            self.assertEqual(self.decision(target), {})
        self.config.write_text("wiki_path: ../vault\n")
        self.assertEqual(self.decision(target)["permissionDecision"], "deny")
        (self.vault / "concepts").rmdir()
        self.assertEqual(self.decision(target), {})
        self.config.unlink()
        self.assertEqual(self.decision(target), {})

    def test_symlink_and_missing_ancestors(self) -> None:
        """Resolve real ancestors before policing a future nested target."""
        link = self.directory / "linked"
        link.symlink_to(self.vault, target_is_directory=True)
        self.assertEqual(self.decision(link / "decisions/deep/new.md")["permissionDecision"], "deny")


if __name__ == "__main__":
    import unittest

    unittest.main()
