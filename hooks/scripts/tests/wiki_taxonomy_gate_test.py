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
        self.schema = self.plugin / "wiki.schema.json"
        self.set_types(["investigations", "concepts"])
        (self.vault / "investigations").mkdir()
        (self.vault / "concepts").mkdir()
        (self.plugin / ".coderails").mkdir()
        self.config = self.plugin / ".coderails/workflow.config.yaml"
        self.config.write_text(f"wiki_path: {self.vault}\n")

    def set_types(self, types: object) -> None:
        """Write the plugin's wiki.schema.json."""
        self.schema.write_text(json.dumps({"page_types": types}))

    def reasons(self) -> list[str]:
        """Trace reason codes written for session S1."""
        trace = self.directory / "state/S1/trace.jsonl"
        return [json.loads(line)["reason_code"] for line in trace.read_text().splitlines()] if trace.exists() else []

    def decision(self, file: Path) -> dict[str, object]:
        """Evaluate one target path using the live plugin schema and configuration."""
        result = self.run_hook(
            "wiki_taxonomy_gate",
            {"session_id": "S1", "cwd": str(self.vault), "tool_input": {"file_path": str(file)}},
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
        self.set_types(["investigations", "concepts", "newtype"])
        self.assertEqual(self.decision(target), {})

    def test_ambiguous_identity_fail_open(self) -> None:
        """An unrelated Git root cannot activate vault policing, and says nothing."""
        self.assertEqual(self.decision(self.plugin / "hooks/new.py"), {})
        self.assertEqual(self.reasons(), [])

    def test_schema_problems_fail_open_with_reason(self) -> None:
        """Negative control: the old gate returned 0 silently; now missing/invalid/empty schema leaves a reason row."""
        target = self.vault / "decisions/a.md"
        self.schema.unlink()
        self.assertEqual(self.decision(target), {})
        for bad in ("not json", "[]", '{"page_types": "x"}', '{"page_types": []}', '{"page_types": [1, "../x"]}'):
            self.schema.write_text(bad)
            self.assertEqual(self.decision(target), {}, bad)
        self.assertEqual(self.reasons(), ["wiki_schema_missing"] + ["wiki_schema_invalid"] * 5)

    def test_unconfigured_wiki_is_silent(self) -> None:
        """Inert (no wiki_path) stays silent even with a broken schema."""
        self.schema.write_text("not json")
        self.config.write_text("wiki_path: null\n")
        self.assertEqual(self.decision(self.vault / "decisions/a.md"), {})
        self.assertEqual(self.reasons(), [])

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
