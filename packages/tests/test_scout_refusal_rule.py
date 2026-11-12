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
HEAD = "**Stop on scout spawn refusal.**"
END = "The skip records let `J2` release."
# Match complete sentences so reversed advice cannot satisfy the test.
COMMON = (
    "If the design scout or a reviewer cannot start, do not use an orchestrator or worker read as the scout.",
    "If no scout can do the check independently, stop the loop and wait for the user.",
    "A `non_independent` fallback needs explicit user approval.",
    "The next direct user reply must be `approve`.",
    "The native record command checks the two transcript messages. It refuses a missing or different reply.",
    "Only after that reply, record `S2.5` as `skipped` with an `evidence` prefix of `non_independent: human approved`.",
    "Run `graph.py record-decision` with that phase and decision text.",
    "A `non_independent` read cannot count as a check by a different agent or as `done`.",
    "If there is no design fork, record `no_design_fork: <reason>` before a scout call.",
)
CODEX_ONLY = (
    "Try the spawn again with the same `task_name`.",
    "A refusal does not satisfy `done`.",
    "Try with a new `task_name`. Do not use the same name.",
)
CLAUDE_ONLY = ("Claude has no `task_name` binding.",)


def rule(path: Path) -> str:
    """Return the scout-refusal section, including its approval and skip rules."""
    text = path.read_text()
    start = text.index(HEAD) + len(HEAD)
    return text[start : text.index(END, start)]


class ScoutRefusalRuleTests(unittest.TestCase):
    """Sentence-anchored guards on the scout-refusal rule."""

    def test_common_sentences_in_both(self) -> None:
        """Both rule sections carry every shared sentence in order."""
        for path in (CLAUDE, CODEX):
            r = rule(path)
            offset = 0
            for sentence in COMMON:
                position = r.find(sentence, offset)
                self.assertGreaterEqual(position, 0, f"{path} missing or reordered sentence {sentence!r}")
                offset = position + len(sentence)

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
        """The graph contract names the machine-readable no-fork exit and the approval limit."""
        text = GRAPH.read_text()
        self.assertIn("no_design_fork: <reason>", text)
        self.assertIn("approval check refuses", text)

    def test_codex_rule_beside_retry_rule(self) -> None:
        """Codex rule sits after the retry rule, before review."""
        text = CODEX.read_text()
        self.assertLess(text.index("try again with the same printed `task_name`"), text.index(HEAD))
        self.assertLess(text.index(HEAD), text.index("## Review and release"))

    def test_codex_design_scout_exists(self) -> None:
        """The Codex doc may not deny a role that ships."""
        self.assertTrue(DESIGN_SCOUT.exists())


if __name__ == "__main__":
    unittest.main()
