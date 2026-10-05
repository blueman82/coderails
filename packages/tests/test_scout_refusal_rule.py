"""Both providers' agentic-loop docs must fail closed when an independent scout cannot be spawned."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from packages.tests.provider_fixture import ROOT

CLAUDE = ROOT / "skills/agentic-loop/phases-setup.md"
CODEX = ROOT / "packages/codex/skills/agentic-loop/SKILL.md"
GRAPH = ROOT / "skills/agentic-loop/execution-graph.md"
DESIGN_SCOUT = ROOT / "packages/codex/agents/design-scout.toml"
HEAD = "**Scout spawn refusal fails closed.**"
# Whole sentences, so a reversed or reordered rule cannot satisfy them.
COMMON = (
    "do not silently downgrade to the orchestrator's or a worker's own read.",
    "Without an independent scout the loop HALTS for the human: do not continue past the refusal.",
    "A `non_independent` fallback requires explicit human approval.",
    "Only after the human approves, record `S2.5` as `skipped` with evidence beginning "
    "`non_independent: human approved`",
    "append a `decisions_absorbed` entry "
    '`{phase: "<current phase>", decision: "scout refused: <error text>, adopted non_independent"}`.',
    "That `skipped` record is the only exit that lets `J2` release without an independent scout;",
    "a `non_independent` read never counts as an independent review or as `done`.",
    "no gate reads `non_independent`, so this is an orchestrator rule, not a hook-enforced one.",
)
CODEX_ONLY = (
    "Retry the spawn with the same `task_name`;",
    "a refused call never satisfies `done`",
    "retry with a FRESH `task_name`, never the same one.",
)
CLAUDE_ONLY = ("Claude has no `task_name`",)


def rule(path: Path) -> str:
    """Return the scout-refusal rule paragraph of a doc."""
    text = path.read_text()
    return text.split(HEAD, 1)[1].split("\n\n", 1)[0]


class ScoutRefusalRuleTests(unittest.TestCase):
    """Sentence-anchored guards on the scout-refusal rule."""

    def test_common_sentences_in_both(self) -> None:
        """Both rule paragraphs carry every shared sentence."""
        for path in (CLAUDE, CODEX):
            r = rule(path)
            for s in COMMON:
                self.assertIn(s, r, f"{path.name} missing sentence {s!r}")

    def test_provider_split(self) -> None:
        """Codex task_name mechanics stay out of the Claude text."""
        c, x = rule(CLAUDE), rule(CODEX)
        for s in CODEX_ONLY:
            self.assertIn(s, x)
        for s in CLAUDE_ONLY:
            self.assertIn(s, c)
        # Claude has no task_name concept beyond saying so; Codex-only mechanics must not leak in.
        self.assertNotIn("same `task_name`", c)
        self.assertNotIn("record-wave` rejects", c)
        self.assertNotIn("Claude has no", x)

    def test_no_continue_past_refusal(self) -> None:
        """The rule never says to continue past a refusal."""
        for path in (CLAUDE, CODEX):
            r = rule(path)
            self.assertNotIn("then continue", r)
            self.assertNotIn("always satisfies", r)

    def test_thread_limit_paragraph_no_version_claim(self) -> None:
        """No version claim about close tools."""
        for path in (CLAUDE, CODEX):
            text = path.read_text()
            self.assertIn("where one exists", text)
            self.assertNotIn("0.149", text)
            self.assertNotIn("expose none", text)

    def test_graph_has_exit(self) -> None:
        """The graph table defines the non_independent exit."""
        self.assertIn("human approved a `non_independent` fallback", GRAPH.read_text())

    def test_codex_rule_beside_retry_rule(self) -> None:
        """Codex rule sits after the retry rule, before review."""
        text = CODEX.read_text()
        self.assertLess(text.index("re-issue it with the same printed `task_name`"), text.index(HEAD))
        self.assertLess(text.index(HEAD), text.index("## Review and release"))

    def test_codex_design_scout_exists(self) -> None:
        """The Codex doc may not deny a role that ships."""
        self.assertTrue(DESIGN_SCOUT.exists())


if __name__ == "__main__":
    unittest.main()
