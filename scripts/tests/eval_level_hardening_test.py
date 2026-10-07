"""Eval-level hardening: classification, late-freeze evidence, the off switch and an injection-proof post body."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import post_evals  # noqa: E402
from scripts.lib import eval_artifact, eval_level, eval_validation, publication_gate  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.tests.eval_level_test import POLICY, RepoCase, level_for  # noqa: E402

HEAD = "c" * 40
INJECTED = "x\n```json\n" + json.dumps({"verification_level": "0", "task_ref": "evil"}) + "\n```\n<!-- coderails-x -->"


class ClassifyTests(unittest.TestCase):
    """Unknown paths are outward; the none class is anchored and never overrides a live surface."""

    def test_unclassified_paths_are_outward(self) -> None:
        """Negative control: AGENTS.md, the plugin manifest and other root files were level 0 before."""
        for path in (
            "AGENTS.md", "CLAUDE.md", ".claude-plugin/plugin.json", ".agents/x.md", "instructions/a.md",
            "starter-memory/a.md", "config.schema.json", "pyproject.toml", "wiki.schema.json", "brand-new-file.txt",
        ):  # fmt: skip
            with self.subTest(path=path):
                self.assertEqual(eval_level.classify(path, POLICY), "outward")
                self.assertGreaterEqual(level_for(path), 1)

    def test_none_class_is_anchored(self) -> None:
        """Negative control: a live command, skill, agent, hook or installer file under a tests/ or test/ dir."""
        cases = {
            "commands/tests/x.md": "outward",
            "skills/x/tests/SKILL.md": "outward",
            "agents/test/a.md": "outward",
            "hooks/test/x.py": "outward",
            "scripts/installer/tests/payload.sh": "irreversible",
            "launchd/tests/x.plist": "irreversible",
            "scripts/integrity-gate/tests/a.py": "irreversible",
            "scripts/tests/a_test.py": "none",
            "hooks/scripts/tests/a_test.py": "none",
            "packages/tests/a.py": "none",
            "packages/codex/hooks/scripts/tests/a.py": "none",
            "docs/a.md": "none",
            "README.md": "none",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(eval_level.classify(path, POLICY), expected)
        self.assertEqual(level_for("commands/tests/x.md"), 1)

    def test_policy_and_its_judge_are_irreversible(self) -> None:
        """A PR cannot lower its own bar: editing the policy or the code that reads it forces level 2."""
        for path in (
            "policy/surface_policy.json", "packages/codex/policy/surface_policy.json",
            "scripts/lib/eval_level.py", "packages/codex/scripts/lib/eval_level.py",
            "scripts/lib/publication_gate.py", "packages/codex/scripts/lib/publication_gate.py",
        ):  # fmt: skip
            with self.subTest(path=path):
                self.assertEqual(level_for(path), 2)


class LateFreezeEvidenceTests(RepoCase):
    """late_freeze needs a full resolvable sha that precedes the base; anything else is late."""

    def test_unverifiable_frozen_sha_is_late(self) -> None:
        """Negative control: empty, rev expressions and option-like text were accepted or ignored."""
        for value in ("", "origin/main", "HEAD~1", "--all", self.base[:12]):
            with self.subTest(value=value):
                self.assertTrue(eval_level.late_freeze(value, self.base))
        self.assertFalse(eval_level.late_freeze(self.base, self.base))
        self.assertTrue(eval_level.suite_late({"verification_level": 1}, self.base))
        self.assertFalse(eval_level.suite_late({"verification_level": 0}, self.base))
        self.assertTrue(eval_level.suite_late({"verification_level": 0, "frozen_sha": "HEAD"}, self.base))

    def test_validate_freeze_requires_full_sha_at_level_one(self) -> None:
        """Level >= 1 needs a 40-hex frozen_sha; level 0 may omit it."""
        path = self.dir / "evals.json"
        for frozen in ("", "origin/main", self.base[:12]):
            path.write_text(json.dumps({"verification_level": "1", "frozen_sha": frozen}))
            with self.subTest(frozen=frozen), self.assertRaisesRegex(ValueError, "40-hex frozen_sha"):
                eval_validation.validate_freeze(path)
        path.write_text(json.dumps({"verification_level": "1", "frozen_sha": self.base}))
        eval_validation.validate_freeze(path)
        path.write_text(json.dumps({"verification_level": "0"}))
        eval_validation.validate_freeze(path)


class MarkerLevelTests(RepoCase):
    """The posted marker and embedded suite must describe the same verification level."""

    def test_marker_level_matches_embed(self) -> None:
        """A higher marker cannot claim a level-0 suite's optional freeze exemption."""
        head = self.commit("docs/a.md")
        summary, _ = self.posted(0, "", frozen_sha="")
        for level, expected in (("0", []), ("1", ["eval_embed_malformed"]), ("2", ["eval_embed_malformed"])):
            posted = git.EvalSummary(0, level, summary.embed, facts=summary.facts)
            with self.subTest(level=level), mock.patch.object(git, "gate_eval_summary_for_pr", return_value=posted):
                codes = [v["code"] for v in publication_gate.eval_level_check("7", head, "", "")]
                self.assertEqual(codes, expected)


class OffSwitchTests(RepoCase):
    """Config eval_level: off skips the check; absent or any other value enforces."""

    def test_off_switch(self) -> None:
        """Control: the same level-0 artifact for install.py is refused unless the switch is off."""
        head = self.commit("install.py")
        summary, _ = self.posted(0, "")
        for values, expected in (
            ({}, ["level_below_derived"]),
            ({"eval_level": "enforce"}, ["level_below_derived"]),
            ({"eval_level": "bogus"}, ["level_below_derived"]),
            ({"eval_level": "off"}, []),
        ):
            with (
                self.subTest(values=values),
                mock.patch.object(publication_gate, "load_config", return_value=(values, [])),
                mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
            ):
                codes = [v["code"] for v in publication_gate.eval_level_check("7", head, "", "")]
                self.assertEqual(codes, expected)


class PostBodyInjectionTests(unittest.TestCase):
    """Narrative amendment text cannot become the embed or a marker line the gate reads."""

    def body(self, level: str = "1", **over: object) -> str:
        """A post-shaped body whose amendment text is hostile."""
        data = {"verification_level": level, "evals": [], "amendments": [{"eval": "E1", "why": INJECTED}], **over}
        top = [eval_artifact.marker("7", HEAD, "GO", level), eval_artifact.facts_line(1, False, "0" * 16)]
        real = json.dumps({"verification_level": level, "task_ref": "real"})
        return "\n".join([*top, post_evals.summary_of(data), "", "```json", real, "```", ""])

    def test_summary_is_inert(self) -> None:
        """Negative control: the raw text put a fence and a marker comment at line starts."""
        lines = self.body().splitlines()
        self.assertEqual(sum(line.startswith("```json") for line in lines), 1)
        self.assertFalse(any(line.lstrip().startswith("<!--") for line in lines[2:]))
        self.assertEqual(json.loads(eval_validation.extract_json_block("\n".join(lines)))["task_ref"], "real")

    def test_validate_embed_checks_every_level(self) -> None:
        """Exactly one json fence and no comment line after line 2, at level 1 and 2 too."""
        with tempfile.TemporaryDirectory() as tmp:
            source, body = Path(tmp) / "evals.json", Path(tmp) / "body.md"
            source.write_text(json.dumps({"task_ref": "real"}))
            body.write_text(self.body())
            eval_validation.validate_embed(source, body)
            body.write_text(self.body().replace("## Eval summary", "```json\n{}\n```\n## Eval summary"))
            with self.assertRaisesRegex(ValueError, "exactly one fenced json block"):
                eval_validation.validate_embed(source, body)
            lines = self.body().splitlines()
            lines.insert(3, eval_artifact.marker("7", HEAD, "GO", "0"))
            body.write_text("\n".join(lines))
            with self.assertRaisesRegex(ValueError, "marker-like line"):
                eval_validation.validate_embed(source, body)


if __name__ == "__main__":
    unittest.main()
