"""Both providers' agentic-loop docs must fail closed when an independent scout cannot be spawned."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import ROOT

DOCS = (
    ROOT / "skills/agentic-loop/phases-setup.md",
    ROOT / "packages/codex/skills/agentic-loop/SKILL.md",
)
RULE_PARAGRAPH = (
    "agent thread limit reached",
    "do not silently downgrade",
    "record the node `failed`",
    "`graph.py record-wave`",
    "`decisions_absorbed`",
    "non_independent",
    "never satisfies an independent-review requirement",
    "halt for the human",
    "No gate reads `non_independent`",
)
REQUIRED = ("Scout spawn refusal", "not_found", "What consumes the thread limit")
DESIGN_SCOUT = ROOT / "packages/codex/agents/design-scout.toml"


class ScoutRefusalRuleTests(unittest.TestCase):
    """Doc-presence guard: the rule wording exists in both docs. It cannot detect a semantic reversal."""

    def test_rule_present_in_both_providers(self) -> None:
        """Each doc carries every required phrase."""
        for path in DOCS:
            text = path.read_text()
            self.assertIn("Scout spawn refusal fails closed", text)
            rule = text.split("Scout spawn refusal fails closed", 1)[1].split("\n\n", 1)[0]
            for phrase in RULE_PARAGRAPH:
                self.assertIn(phrase, rule, f"{path.relative_to(ROOT)} rule paragraph missing {phrase!r}")
            self.assertNotIn("no separate design-scout role", text)
            self.assertNotIn("evidence string", text)
            for phrase in REQUIRED:
                self.assertIn(phrase, text, f"{path.relative_to(ROOT)} missing {phrase!r}")

    def test_codex_design_scout_exists(self) -> None:
        """The Codex doc may not deny a role that ships."""
        self.assertTrue(DESIGN_SCOUT.exists())


if __name__ == "__main__":
    unittest.main()
