"""Review controls for policy self-edits and false posted minimum facts."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from scripts.lib import eval_level, publication_gate
from scripts.lib import git_common as git
from scripts.tests.eval_level_test import RepoCase


class ReviewRepairTests(RepoCase):
    """A PR cannot lower its own eval floor or forge the stamped floor."""

    def check(self, summary: git.EvalSummary) -> list[str]:
        """Run the publication check against this temporary PR head."""
        head = self.git("rev-parse", "HEAD")
        with mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary):
            return [item["code"] for item in publication_gate.eval_level_check("7", head, "", "")]

    def test_policy_edit_cannot_lower_its_own_pr_floor(self) -> None:
        """A valid policy edited in this PR cannot classify that same edit as level 0."""
        weakened = {"none": ["**"], "irreversible": [], "outward": [], "level_2_work_units": 999}
        path = self.dir / "weakened-policy.json"
        path.write_text(json.dumps(weakened))
        policy = eval_level.load_policy(path)
        protected = (
            "policy/surface_policy.json",
            "packages/codex/policy/surface_policy.json",
            "scripts/lib/eval_level.py",
            "packages/codex/scripts/lib/eval_level.py",
            "scripts/lib/publication_gate.py",
            "packages/codex/scripts/lib/publication_gate.py",
        )
        for name in protected:
            with self.subTest(name=name):
                facts, minimum = eval_level.derive([("M", [name])], 0, {}, policy)
                self.assertEqual((facts["surfaces"], minimum), (["irreversible"], 2))
        self.commit("policy/surface_policy.json")
        with mock.patch.object(eval_level, "load_policy", return_value=policy):
            self.assertIn("level_below_derived", self.check(self.posted(0, "")[0]))

    def test_posted_minimum_must_equal_recomputed_minimum(self) -> None:
        """A facts line cannot claim a different minimum while other stamps remain valid."""
        self.commit("docs/a.md")
        self.assertEqual(self.check(self.posted(0, "", derived=0)[0]), [])
        self.assertIn("eval_facts_level_mismatch", self.check(self.posted(0, "", derived=2)[0]))
        self.git("reset", "-q", "--hard", self.base)
        self.commit("install.py")
        self.assertEqual(self.check(self.posted(2, "", derived=2)[0]), [])
        self.assertIn("eval_facts_level_mismatch", self.check(self.posted(2, "", derived=0)[0]))


if __name__ == "__main__":
    unittest.main()
