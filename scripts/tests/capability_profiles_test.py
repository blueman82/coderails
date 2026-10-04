"""Pin the single-source capability profiles against Claude frontmatter and Codex sandbox modes."""

from __future__ import annotations

import copy
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.lib.capability_profiles import guarded_agents, load_profiles  # noqa: E402
from scripts.capability_profiles_validate import validate  # noqa: E402

OLD_GUARDED = {"deploy-safety-reviewer", "design-scout", "disposition-scout", "preflight-scout", "source-auditor"}


def drop_tools(text: str) -> str:
    """Delete the frontmatter `tools:` line."""
    return re.sub(r"(?m)^tools:.*\n", "", text)


def set_tools(text: str, replace: str | None, append: str = "") -> str:
    """Replace the `tools:` value with `replace`, or append `append` to it."""
    if replace is not None:
        return re.sub(r"(?m)^tools:.*$", lambda _m: "tools:" + replace, text)
    return re.sub(r"(?m)^tools:.*$", lambda m: m.group(0) + append, text)


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

    def test_string_capability_value_is_rejected_at_load(self) -> None:
        """A string where a list belongs would turn `in` into a substring test; refuse it."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "capabilities").mkdir()
            (Path(tmp) / "capabilities" / "profiles.json").write_text(json.dumps({"agents": {"a": "shell.raw"}}))
            with self.assertRaises(ValueError):
                load_profiles(Path(tmp))

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

    def _with_agent_edit(self, name: str, edit: Callable[[str], str]) -> list[str]:
        """Validate a scratch copy of the repo after `edit(text) -> text` is applied to agents/<name>.md."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO / "agents", root / "agents")
            shutil.copytree(REPO / "packages/codex/agents", root / "packages/codex/agents")
            path = root / "agents" / f"{name}.md"
            path.write_text(edit(path.read_text()))
            return validate(root, self.profiles)

    def test_missing_tools_line_is_red(self) -> None:
        """Negative control: no `tools:` line means ALL tools for the harness, so it must not pass."""
        errors = self._with_agent_edit("spec-reviewer", drop_tools)
        self.assertTrue(any("spec-reviewer" in e and "tools:" in e for e in errors), errors)

    def test_yaml_list_tools_is_red(self) -> None:
        """A block-list `tools:` parses as empty and is refused rather than read as zero tools."""
        errors = self._with_agent_edit("spec-reviewer", lambda t: set_tools(t, "\n  - Read"))
        self.assertTrue(any("spec-reviewer" in e and "tools:" in e for e in errors), errors)

    def test_extra_ungated_tools_are_red(self) -> None:
        """Negative control: Task/WebFetch/mcp__ on a guarded agent is drift, Skill is not allowed on a scout."""
        extra = ", Task, WebFetch, mcp__x__y, Skill"
        errors = self._with_agent_edit("design-scout", lambda t: set_tools(t, None, extra))
        joined = " ".join(errors)
        for tool in ("Task", "WebFetch", "mcp__x__y", "Skill"):
            self.assertIn(tool, joined)
        self.assertEqual(self._with_agent_edit("preflight-scout", lambda t: t), [])  # its Skill is allowlisted

    def test_source_auditor_has_tests_run_and_scouts_do_not(self) -> None:
        """The narrow execution capability is granted to exactly one agent."""
        holders = {a for a, caps in self.profiles["agents"].items() if "tests.run" in caps}
        self.assertEqual(holders, {"source-auditor"})


if __name__ == "__main__":
    unittest.main()
