"""PR-base evaluation controls over a release branch and a disappearing base lookup."""

from __future__ import annotations

import unittest
from unittest import mock

from scripts.lib import eval_level
from scripts.lib import git_common as git
from scripts.tests.eval_level_test import POLICY, RepoCase


class ReleaseBaseTests(RepoCase):
    """Release-targeted PRs must retain the target's evaluation floor and freeze ancestry."""

    def test_release_pr_uses_its_base_for_level_and_freeze(self) -> None:
        """An install change already on newer main still makes a release PR level 2."""
        self.commit("install.py")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        head = self.commit("docs/a.md")
        with mock.patch.object(git, "pr_field", return_value=self.base):
            changes = eval_level.pr_changes("7", head)
            self.assertIsNotNone(changes)
            self.assertEqual(eval_level.derive(changes or [], 0, {}, POLICY)[1], 2)
            self.assertEqual(eval_level.branch_base(head, pr="7"), self.base)
            self.assertTrue(eval_level.suite_late({"frozen_sha": self.git("rev-parse", "origin/main")}, self.base))

    def test_pr_base_disappearing_after_diff_refuses_freeze(self) -> None:
        """A later missing base cannot certify a freeze as on time."""
        head = self.commit("install.py")
        with mock.patch.object(git, "pr_field", side_effect=[self.base, ""]):
            self.assertIsNotNone(eval_level.pr_changes("7", head))
            with self.assertRaisesRegex(ValueError, "eval_level_diff_unavailable"):
                eval_level.branch_base(head, pr="7")


if __name__ == "__main__":
    unittest.main()
