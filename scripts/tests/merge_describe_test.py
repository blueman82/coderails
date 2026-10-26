"""merge.py --describe: one source for the gate list, no gh contact, and no $ARGUMENTS in command code blocks."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import ModuleType
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import merge  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import publication_gate  # noqa: E402

GH_SPY = '#!/bin/sh\necho "$@" >> "$GH_LOG"\nexit 1\n'
FENCE = re.compile(r"```.*?```", re.DOTALL)
# the gate names before this change was made, frozen so a removed gate cannot silently shrink a hand-written list
CHECKS_BEFORE = ["manifest_check", "review_passes_check", "eval_level_check"]


def described(module: ModuleType) -> dict[str, list[dict[str, str]]]:
    """The --describe payload as the module builds it."""
    payload: dict[str, list[dict[str, str]]] = json.loads(module.describe())
    return payload


class DescribeTests(unittest.TestCase):
    """--describe prints the registry and never reaches gh or a branch lookup."""

    def test_describe_exits_zero_without_contacting_gh_and_is_not_a_branch(self) -> None:
        """A spy gh on PATH is never called; --describe is handled before the positional target."""
        with tempfile.TemporaryDirectory() as directory:
            spy = Path(directory) / "gh"
            spy.write_text(GH_SPY)
            spy.chmod(spy.stat().st_mode | stat.S_IXUSR)
            log = Path(directory) / "gh.log"
            env = {**os.environ, "PATH": f"{directory}:{os.environ['PATH']}", "GH_LOG": str(log)}
            result = subprocess.run(
                [sys.executable, str(REPO / "scripts/merge.py"), "--describe"],
                cwd=directory,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(log.exists(), "gh was contacted")
            payload = json.loads(result.stdout)
            self.assertEqual([g["name"] for g in payload["publication_gate"]], CHECKS_BEFORE)

    def test_described_list_equals_the_gates_actually_invoked(self) -> None:
        """Replace every registered gate and stage with a recorder: describe lists exactly what evaluate/verify run."""
        calls: list[str] = []

        def recorder(name: str) -> object:
            def check(*args: object, **kwargs: object) -> list[object]:
                calls.append(name)
                return []

            check.__name__ = name
            check.__doc__ = f"{name} summary."
            return check

        stages = [(n, recorder(n)) for n in ("stage_a", "stage_b", "stage_c")]
        checks = [recorder(n) for n in ("check_a", "check_b")]
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(merge, "VERIFY_STAGES", stages))
            stack.enter_context(mock.patch.object(publication_gate, "CHECKS", checks))
            stack.enter_context(mock.patch.object(git, "pr_field", return_value="abc"))
            stack.enter_context(mock.patch.object(git, "repo", return_value="r"))
            merge.verify_gates("7")
            publication_gate.evaluate("7", "abc")
            payload = described(merge)
        self.assertEqual(
            calls, [g["name"] for g in payload["verify_gates"]] + [g["name"] for g in payload["publication_gate"]]
        )
        self.assertEqual([g["summary"] for g in payload["publication_gate"]], ["check_a summary.", "check_b summary."])

    def test_a_gate_removed_from_the_registry_changes_the_description(self) -> None:
        """Negative control: a hand-written list would still show the removed gate; the generated one does not."""
        with mock.patch.object(publication_gate, "CHECKS", publication_gate.CHECKS[:-1]):
            names = [g["name"] for g in described(merge)["publication_gate"]]
        self.assertNotEqual(names, CHECKS_BEFORE)
        self.assertEqual(names, CHECKS_BEFORE[:-1])

    def test_real_registry_is_described(self) -> None:
        """The shipped stages and checks are all present, in call order."""
        payload = described(merge)
        self.assertEqual([g["name"] for g in payload["verify_gates"]], [n for n, _ in merge.VERIFY_STAGES])
        self.assertEqual(
            [g["name"] for g in payload["publication_gate"]], [c.__name__ for c in publication_gate.CHECKS]
        )
        self.assertTrue(all(g["summary"] for g in payload["verify_gates"] + payload["publication_gate"]))


class ArgumentsInterpolationTests(unittest.TestCase):
    """No command or skill puts $ARGUMENTS inside a fenced code block (extends the post-review/post-evals greps)."""

    def test_no_arguments_interpolation_in_fenced_code(self) -> None:
        """Four files stay free of $ARGUMENTS inside fences; merge.md no longer carries the hand-written list."""
        for relative in (
            "commands/merge.md",
            "packages/codex/skills/merge/SKILL.md",
            "commands/post-review.md",
            "commands/post-evals.md",
        ):
            with self.subTest(file=relative):
                text = (REPO / relative).read_text()
                for block in FENCE.findall(text):
                    self.assertNotIn("$ARGUMENTS", block)
        merge_md = (REPO / "commands/merge.md").read_text()
        self.assertNotIn("$ARGUMENTS", merge_md)
        self.assertNotIn("The script handles:", merge_md)
        self.assertIn("merge.py", merge_md)
        self.assertIn("--describe", merge_md)


if __name__ == "__main__":
    unittest.main()
