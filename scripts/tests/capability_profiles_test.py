"""Pin the single-source capability profiles against Claude frontmatter and Codex sandbox modes."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.lib.capability_profiles import guarded_agents, load_profiles  # noqa: E402
from scripts.capability_profiles_validate import validate  # noqa: E402

OLD_GUARDED = {"deploy-safety-reviewer", "design-scout", "disposition-scout", "preflight-scout", "source-auditor"}


class ProfileTests(unittest.TestCase):
    """Every shipped agent has a profile and each harness's declared limits agree with it."""

    def setUp(self) -> None:
        """Load the checked-in profiles once per case."""
        self.profiles = load_profiles(REPO)

    def test_checked_in_profiles_validate(self) -> None:
        """No drift between profiles.json, agents/*.md and packages/codex/agents/*.toml."""
        self.assertEqual(validate(REPO, self.profiles), [])

    def test_guarded_set_is_derived_and_unchanged(self) -> None:
        """Bash-bearing agents without shell.raw are exactly the pre-existing hard-coded set."""
        self.assertEqual(set(guarded_agents(self.profiles)), OLD_GUARDED)

    def test_missing_profile_is_red(self) -> None:
        """Negative control: deleting a profile is reported for both harnesses."""
        broken = copy.deepcopy(self.profiles)
        del broken["agents"]["design-scout"]
        errors = validate(REPO, broken)
        self.assertTrue(any("design-scout" in e and "no profile" in e for e in errors), errors)

    def test_write_on_read_only_agent_is_red(self) -> None:
        """Negative control: granting worktree.write to a read-only agent disagrees with frontmatter and sandbox."""
        broken = copy.deepcopy(self.profiles)
        broken["agents"]["design-scout"].append("worktree.write")
        errors = validate(REPO, broken)
        self.assertTrue(any("design-scout" in e and "claude" in e for e in errors), errors)
        self.assertTrue(any("design-scout" in e and "codex" in e for e in errors), errors)

    def test_unknown_capability_and_missing_instruction_are_red(self) -> None:
        """A made-up capability, or tests.run without agent text naming capability.py, fails."""
        broken = copy.deepcopy(self.profiles)
        broken["agents"]["design-scout"] += ["bogus.cap", "tests.run"]
        errors = validate(REPO, broken)
        self.assertTrue(any("bogus.cap" in e for e in errors), errors)
        self.assertTrue(any("design-scout" in e and "capability.py" in e for e in errors), errors)

    def test_source_auditor_has_tests_run_and_scouts_do_not(self) -> None:
        """The narrow execution capability is granted to exactly one agent."""
        holders = {a for a, caps in self.profiles["agents"].items() if "tests.run" in caps}
        self.assertEqual(holders, {"source-auditor"})


if __name__ == "__main__":
    unittest.main()
