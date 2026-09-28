"""Preserve branch counters, command matching, fail-closed writes, and lock cleanup."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.native_hook_test_support import HookCase


class CeilingTests(HookCase):
    """Python caller migration must never reset or bypass existing volume limits."""

    def setUp(self) -> None:
        """Create a known branch and private counter storage."""
        super().setUp()
        self.repo = self.repository("repo", "unit-test")
        self.full = "python3 hooks/scripts/tests/run_all.py"
        self.post = "python3 scripts/post_evals.py validate-structure evals.json 5 abc123"

    def request(self, command: str, repo: Path | None = None, **fields: object) -> dict[str, Any]:
        """Build a native Bash request for the chosen branch."""
        return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo or self.repo), **fields}

    def count(self, target: str, branch: str = "unit-test") -> Path:
        """Return the existing persistent counter filename."""
        return self.loop / "verification-ceiling" / f"{branch}__{target}.count"

    def test_third_invocation_and_separate_targets(self) -> None:
        """The third call denies with one JSON response and always releases its lock."""
        for command, target in ((self.full, "run_all"), (self.post, "post_evals")):
            for expected in (False, False, True, True):
                self.assertEqual(self.denied("verification_volume_ceiling", self.request(command)), expected)
            self.assertEqual(self.count(target).read_text(encoding="utf-8").strip(), "4")
            self.assertFalse(Path(f"{self.count(target)}.lock").exists())

    def test_existing_counter_survives_python_cutover(self) -> None:
        """A preexisting count blocks the first Python invocation without a reset."""
        counter = self.count("run_all")
        counter.parent.mkdir(parents=True)
        counter.write_text("2\n", encoding="utf-8")
        self.assertTrue(self.denied("verification_volume_ceiling", self.request(self.full)))
        self.assertEqual(counter.read_text(encoding="utf-8").strip(), "3")

    def test_children_and_branch_isolation(self) -> None:
        """A child never counts; other branches retain independent top-level counts."""
        self.assertEqual(self.output("verification_volume_ceiling", self.request(self.full, agent_id="agent-1")), {})
        self.assertFalse(self.count("run_all").exists())
        self.assertFalse(self.denied("verification_volume_ceiling", self.request(self.full)))
        self.assertFalse(self.denied("verification_volume_ceiling", self.request(self.full)))
        other = self.repository("other", "unit-other")
        self.assertFalse(self.denied("verification_volume_ceiling", self.request(self.full, repo=other)))
        self.assertEqual(self.count("run_all", "unit-other").read_text(encoding="utf-8").strip(), "1")

    def test_noninvocations_and_other_subcommands(self) -> None:
        """Mentions and unrelated post-eval subcommands are not invocations of a capped operation."""
        commands = ["npm test", "grep -n run_all.py hooks/hooks.json", "cat hooks/scripts/tests/run_all.py"]
        commands.extend(
            f"python3 scripts/post_evals.py {name} evals.json"
            for name in ("compute-result", "validate-discriminating", "validate-embed")
        )
        for command in commands:
            for _ in range(5):
                self.assertFalse(self.denied("verification_volume_ceiling", self.request(command)))
        self.assertFalse(self.count("run_all").exists())
        self.assertFalse(self.count("post_evals").exists())

    def test_state_directory_and_count_write_failures(self) -> None:
        """Infrastructure errors deny with their specific cause instead of a fake volume violation."""
        bad = self.directory / "not-a-directory"
        bad.touch()
        output = self.output("verification_volume_ceiling", self.request(self.full), CLAUDE_AGENTIC_LOOP_DIR=str(bad))[
            "hookSpecificOutput"
        ]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("state directory", output["permissionDecisionReason"])
        self.assertNotIn("3rd+", output["permissionDecisionReason"])
        self.count("run_all").mkdir(parents=True)
        output = self.output("verification_volume_ceiling", self.request(self.full))["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("count file", output["permissionDecisionReason"])
        self.assertNotIn("3rd+", output["permissionDecisionReason"])
        self.assertFalse(Path(f"{self.count('run_all')}.lock").exists())

    def test_contended_lock_is_not_removed(self) -> None:
        """Timeout denies and preserves the other invocation's lock directory."""
        lock = Path(f"{self.count('run_all')}.lock")
        lock.mkdir(parents=True)
        output = self.output("verification_volume_ceiling", self.request(self.full))["hookSpecificOutput"]
        self.assertEqual(output["permissionDecision"], "deny")
        self.assertIn("lock", output["permissionDecisionReason"])
        self.assertNotIn("3rd+", output["permissionDecisionReason"])
        self.assertTrue(lock.is_dir())


if __name__ == "__main__":
    unittest.main()
