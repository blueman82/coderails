"""The opt-in ruleset definition must match the repo's merge path and stay inert."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
GITHUB_ACTIONS_APP_ID = 15368
RULESET = ROOT / "docs/external-enforcement/ruleset.json"


def check(data: dict[str, Any]) -> list[str]:
    """Return every violated invariant of the ruleset definition."""
    types = {rule["type"]: rule.get("parameters", {}) for rule in data["rules"]}
    problems: list[str] = []
    checks = types.get("required_status_checks", {}).get("required_status_checks", [])
    if [c["context"] for c in checks] != ["verify"]:
        problems.append("required_status_checks must name verify")
    if any(c.get("integration_id") != GITHUB_ACTIONS_APP_ID for c in checks):
        problems.append("required check must be bound to the GitHub Actions integration_id")
    if data["bypass_actors"] != []:
        problems.append("bypass_actors must be empty")
    if types.get("pull_request", {}).get("allowed_merge_methods") != ["merge"]:
        problems.append("allowed_merge_methods must be [merge]")
    if types.get("pull_request", {}).get("required_approving_review_count") != 0:
        problems.append("approvals must stay 0 (same identity cannot self-approve)")
    if "required_linear_history" in types:
        problems.append("required_linear_history breaks gh pr merge --merge")
    problems += [f"{t} rule missing" for t in ("non_fast_forward", "deletion") if t not in types]
    return problems


class RulesetTests(unittest.TestCase):
    """Parse the checked-in JSON and prove each invariant, with negative controls."""

    def setUp(self) -> None:
        """Load the definition fresh for each case."""
        self.data = json.loads(RULESET.read_text())

    def test_shipped_ruleset_is_clean(self) -> None:
        """No invariant is violated by the checked-in file."""
        self.assertEqual(check(self.data), [])

    def test_negative_control_linear_history(self) -> None:
        """Putting required_linear_history back must go red."""
        self.data["rules"].append({"type": "required_linear_history"})
        self.assertIn("required_linear_history breaks gh pr merge --merge", check(self.data))

    def test_negative_control_bypass_and_missing_rules(self) -> None:
        """A bypass actor, a missing deletion rule, or a wrong check name goes red."""
        self.data["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole"}]
        self.data["rules"] = [r for r in self.data["rules"] if r["type"] != "deletion"]
        self.data["rules"][-1]["parameters"]["required_status_checks"] = [{"context": "other"}]
        self.assertEqual(len(check(self.data)), 4)  # bypass, deletion, check name, unbound check

    def test_negative_control_unbound_check(self) -> None:
        """A check without integration_id (any identity could post a status) goes red."""
        del self.data["rules"][-1]["parameters"]["required_status_checks"][0]["integration_id"]
        self.assertIn("required check must be bound to the GitHub Actions integration_id", check(self.data))

    def test_template_installs_every_tool_python_checks_requires(self) -> None:
        """The runner must install the tools quality_tools demands, or SUITE_FAIL is certain."""
        template = (ROOT / "docs/external-enforcement/verify.yml.template").read_text()
        for tool in ("ruff", "black", "pyright", "mypy"):
            self.assertIn(tool, template)
        self.assertIn("npm ci", template)

    def test_readme_states_verifier_is_pr_controlled_and_status_caveat(self) -> None:
        """The trust analysis must not overstate independence."""
        readme = (ROOT / "docs/external-enforcement/README.md").read_text()
        self.assertIn("verifier code is also PR-controlled", readme)
        self.assertIn("integration_id", readme)

    def test_no_workflow_files_added(self) -> None:
        """Nothing under .github/workflows is added relative to origin/main."""
        added = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "diff",
                "--name-only",
                "--diff-filter=A",
                "origin/main",
                "--",
                ".github/workflows",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(added.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
