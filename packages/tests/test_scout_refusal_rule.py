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
REQUIRED = (
    "Scout spawn refusal",
    "not_found",
    "non_independent",
    "never satisfies an independent-review requirement",
    "halt for the human",
    "What consumes the thread limit",
    "do not silently downgrade",
    "Record the refusal",
)
# Must sit together in the single rule paragraph, not merely somewhere in the file.
RULE_PARAGRAPH = (
    "agent thread limit reached",
    "do not silently downgrade",
    "Record the refusal",
    "non_independent",
    "never satisfies an independent-review requirement",
    "halt for the human",
)


class ScoutRefusalRuleTests(unittest.TestCase):
    """Guard the scout-refusal rule text."""

    def test_rule_present_in_both_providers(self) -> None:
        """Each doc carries every required phrase."""
        for path in DOCS:
            text = path.read_text()
            self.assertIn("Scout spawn refusal fails closed", text)
            rule = text.split("Scout spawn refusal fails closed", 1)[1].split("\n\n", 1)[0]
            for phrase in RULE_PARAGRAPH:
                self.assertIn(phrase, rule, f"{path.relative_to(ROOT)} rule paragraph missing {phrase!r}")
            for phrase in REQUIRED:
                self.assertIn(phrase, text, f"{path.relative_to(ROOT)} missing {phrase!r}")


if __name__ == "__main__":
    unittest.main()
