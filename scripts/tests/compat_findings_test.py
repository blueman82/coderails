"""The compat-findings line: builder/parser, `post_review.py compat-line` and the merge refusal on both providers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CODEX = ROOT / "packages/codex"
sys.path.insert(0, str(ROOT))
from hooks.scripts.lib.pr_merge_gate import merge_reason  # noqa: E402
from hooks.scripts.tests.lib.hook_test_support import HookTestCase  # noqa: E402
from scripts.lib import review_artifact  # noqa: E402
from scripts.lib.git_common import EvalSummary  # noqa: E402

MODULE = "hooks.scripts.lib.pr_merge_gate"

SHA = "deadbeef"
V1 = f"<!-- coderails-review-summary v1 pr=42 head_sha={SHA} -->"
GATE = textwrap.dedent("""
    import json, sys
    from unittest.mock import patch
    sys.path.insert(0, sys.argv[1])
    from scripts import merge
    from scripts.lib import git_common as git

    bodies = json.loads(sys.argv[2])
    with (
        patch.object(git, "pr_field", return_value="deadbeef"),
        patch.object(git, "trusted_comment_bodies", return_value=bodies),
        patch.object(git, "gate_eval_summary_for_pr", return_value=git.EvalSummary(1)),
    ):
        try:
            merge.verify_gates("42")
        except git.WorkflowError as error:
            print(error)
    """)


def compat(count: int, disposition: str, sha: str = SHA) -> str:
    """The typed line for PR 42."""
    return review_artifact.compat_line("42", sha, count, disposition)


class MarkerTests(unittest.TestCase):
    """Builder and parser agree; the original v1 marker is untouched."""

    def test_round_trip(self) -> None:
        """A built line parses back to (count, disposition) only for its own PR and head."""
        line = compat(3, "clean-break")
        expected = f"<!-- coderails-compat-findings v1 pr=42 head_sha={SHA} count=3 disposition=clean-break -->"
        self.assertEqual(line, expected)
        self.assertEqual(review_artifact.parse_compat_line(line, "42", SHA), (3, "clean-break"))
        self.assertIsNone(review_artifact.parse_compat_line(line, "43", SHA))
        self.assertIsNone(review_artifact.parse_compat_line(line, "42", "other"))
        self.assertIsNone(review_artifact.parse_compat_line(line + " ", "42", SHA))

    def test_bad_builder_input_is_refused(self) -> None:
        """Negative counts and unknown dispositions never produce a line."""
        for count, disposition in ((-1, "clean-break"), (1, "fork")):
            with self.assertRaises(ValueError):
                review_artifact.compat_line("42", SHA, count, disposition)

    def test_original_marker_is_byte_identical(self) -> None:
        """The root-owned daemon matches this exact v1 line; it must not change."""
        self.assertEqual(review_artifact.marker("42", SHA), V1)
        for name in ("review_artifact.py", "git_common.py"):
            self.assertEqual((ROOT / "scripts/lib" / name).read_bytes(), (CODEX / "scripts/lib" / name).read_bytes())


class CompatLineCliTests(unittest.TestCase):
    """`post_review.py compat-line` prints the same typed line on both providers."""

    def run_cli(self, root: Path, *rest: str) -> subprocess.CompletedProcess[str]:
        """Invoke one provider's post_review.py."""
        argv = [sys.executable, str(root / "scripts/post_review.py"), "compat-line", "42", SHA, *rest]
        return subprocess.run(argv, capture_output=True, text=True, check=False)

    def test_both_providers_print_the_line(self) -> None:
        """Exit 0 and the exact line; a bad disposition or count exits nonzero with nothing on stdout."""
        for root in (ROOT, CODEX):
            with self.subTest(root=root.name):
                done = self.run_cli(root, "--count", "2", "--disposition", "preserve-compat")
                self.assertEqual((done.returncode, done.stdout.strip()), (0, compat(2, "preserve-compat")), done.stderr)
                for bad in (("--count", "-1", "--disposition", "clean-break"), ("--count", "1", "--disposition", "x")):
                    refused = self.run_cli(root, *bad)
                    self.assertNotEqual(refused.returncode, 0)
                    self.assertEqual(refused.stdout, "")


class MergeGateTests(unittest.TestCase):
    """merge.py requires current-head compatibility findings and refuses incompatible clean breaks."""

    def verdict(self, root: Path, *lines: str) -> str:
        """The WorkflowError message verify_gates raises for a trusted comment holding these lines."""
        body = "\n".join([V1, "## No findings", *lines])
        done = subprocess.run(
            [sys.executable, "-c", GATE, str(root), json.dumps([body])], capture_output=True, text=True, check=False
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_each_provider(self) -> None:
        """Refusal reaches the eval gate only when the compat verdict allows it."""
        passes = "No coderails eval artifact"  # the next gate after the review gate
        for root in (ROOT, CODEX):
            with self.subTest(provider=root.name):
                self.assertIn("compat_findings_nonzero", self.verdict(root, compat(3, "clean-break")))
                self.assertIn(passes, self.verdict(root, compat(0, "clean-break")))
                self.assertIn(passes, self.verdict(root, compat(3, "preserve-compat")))
                self.assertIn(passes, self.verdict(root))
                self.assertIn(passes, self.verdict(root, compat(3, "clean-break", "otherhead")))
                broken = self.verdict(root, "<!-- coderails-compat-findings v1 pr=42 -->")
                self.assertIn("compat_findings_malformed", broken)
                mixed = self.verdict(root, compat(0, "clean-break"), compat(3, "clean-break"))
                self.assertIn("compat_findings_nonzero", mixed)  # fail closed: any refusing line for this head wins
                stale = "<!-- coderails-compat-findings v1 pr=42 head_sha=old count=bad -->"
                self.assertIn(passes, self.verdict(root, stale, compat(0, "clean-break")))


class DirectMergeTests(HookTestCase):
    """Keep direct merge behavior aligned with the compatibility review result."""

    def test_direct_merge_refuses_compat_findings(self) -> None:
        """The direct gh merge hook enforces the same review refusal as merge.py."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with (
            patch(MODULE + ".pr_field", return_value="head"),
            patch(MODULE + ".gate_review_summary_for_pr", return_value=(3, "compat_findings_clean_break")),
            patch(MODULE + ".gate_eval_summary_for_pr", return_value=EvalSummary(0, "1", "{}", "")),
            patch(MODULE + ".smoke_verify", return_value=0),
            patch(MODULE + ".integrity_reason", return_value=""),
            patch(MODULE + ".publication_gate.evaluate", return_value=[]),
        ):
            self.assertIn("compat_findings_clean_break", merge_reason("1", str(self.directory)))

    def test_direct_merge_keeps_existing_review_invocation_contract(self) -> None:
        """An absent artifact is handled by the existing invocation gate; an invalid one is refused here."""
        before = Path.cwd()
        self.addCleanup(os.chdir, before)
        with (
            patch(MODULE + ".pr_field", return_value="head"),
            patch(MODULE + ".gate_review_summary_for_pr", return_value=(1, "")),
            patch(MODULE + ".gate_eval_summary_for_pr", return_value=EvalSummary(0, "1", "{}", "")),
            patch(MODULE + ".smoke_verify", return_value=0),
            patch(MODULE + ".integrity_reason", return_value=""),
            patch(MODULE + ".publication_gate.evaluate", return_value=[]),
        ):
            self.assertEqual(merge_reason("1", str(self.directory)), "")


if __name__ == "__main__":
    unittest.main()
