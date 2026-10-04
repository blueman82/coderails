"""ci_verify exits with stable reason codes and reuses (never forks) the existing merge-gate logic."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests import fake_gh_support as fake
from scripts import ci_verify, post_evals
from scripts.lib import git_common

ROOT = Path(__file__).resolve().parents[3]
HEAD = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
OLD = "0" * 40
PASS = [[sys.executable, "-c", "pass"]]
FAIL = [[sys.executable, "-c", "raise SystemExit(1)"]]


def review(sha: str) -> str:
    """Review marker comment body."""
    return f"<!-- coderails-review-summary v1 pr=7 head_sha={sha} -->\nreview"


def evals(sha: str, result: str = "GO") -> str:
    """Eval marker comment with an empty level-0 embed (smoke_verify has nothing to run)."""
    marker = f"<!-- coderails-eval-summary v1 pr=7 head_sha={sha} result={result} verification_level=0 -->"
    return marker + '\n```json\n{"evals": [], "verification_level": "0"}\n```'


def comments(*bodies: str) -> dict[str, Any]:
    """Fake-gh route returning bodies as the base64 lines trusted_comment_bodies expects."""
    return {
        "match": "issues/7/comments",
        "stdout": "".join(base64.b64encode(b.encode()).decode() + "\n" for b in bodies),
    }


class CiVerifyTests(unittest.TestCase):
    """Run main() in-process against a fake gh with stubbed suite commands."""

    def setUp(self) -> None:
        """Pin trust env, point gh at the fake, isolate trace output."""
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def verify(
        self, routes: list[dict[str, Any]], suites: list[list[str]] = PASS, sha: str = HEAD, pr_head: str = HEAD
    ) -> tuple[int, str]:
        """Run ci_verify.main and return (exit code, stdout)."""
        env = {
            **fake.install(self.tmp, [{"match": "pr view 7", "stdout": pr_head + "\n"}, *routes]),
            "_PR_TRUSTED_LOGIN": "blueman82",
            "_PR_TRUSTED_PERMISSION": "WRITE",
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp / "loops"),
        }
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(ci_verify, "SUITES", suites), redirect_stdout(out):
            code = ci_verify.main(["--pr", "7", "--sha", sha])
        return code, out.getvalue()

    def reason(self, out: str) -> str:
        """Extract the REASON= code."""
        return str(re.findall(r"REASON=(\w+)", out)[-1])

    def test_all_green(self) -> None:
        """Suites pass and exact-head review plus GO eval give exit 0."""
        code, out = self.verify([comments(review(HEAD), evals(HEAD))])
        self.assertEqual((code, self.reason(out)), (0, "OK"))

    def test_suite_failure(self) -> None:
        """A failing suite command is SUITE_FAIL."""
        code, out = self.verify([comments(review(HEAD), evals(HEAD))], suites=FAIL)
        self.assertEqual((code != 0, self.reason(out)), (True, "SUITE_FAIL"))

    def test_foreign_sha_refused(self) -> None:
        """A sha that is neither the PR head nor the checkout is SHA_MISMATCH, before anything runs."""
        code, out = self.verify([comments(review(OLD), evals(OLD))], sha=OLD)
        self.assertEqual((code != 0, self.reason(out)), (True, "SHA_MISMATCH"))

    def test_pr_head_moved(self) -> None:
        """The PR head differing from the checked-out sha is SHA_MISMATCH."""
        code, out = self.verify([comments(review(HEAD), evals(HEAD))], pr_head=OLD)
        self.assertEqual((code != 0, self.reason(out)), (True, "SHA_MISMATCH"))

    def test_missing_review(self) -> None:
        """No review artifact is REVIEW_ABSENT."""
        code, out = self.verify([comments(evals(HEAD))])
        self.assertEqual((code != 0, self.reason(out)), (True, "REVIEW_ABSENT"))

    def test_stale_review_older_head(self) -> None:
        """A review bound to an older head counts as stale (SHA-bound), hence absent."""
        code, out = self.verify([comments(review(OLD), evals(HEAD))])
        self.assertEqual((code != 0, self.reason(out)), (True, "REVIEW_ABSENT"))

    def test_missing_eval_stale_eval_and_nogo(self) -> None:
        """No eval, an eval for an older head, and a NO-GO eval all map to EVAL_ABSENT_OR_NOGO."""
        for body in ("", evals(OLD), evals(HEAD, "NO-GO")):
            with self.subTest(body=body[:60]):
                code, out = self.verify([comments(review(HEAD), body)])
                self.assertEqual((code != 0, self.reason(out)), (True, "EVAL_ABSENT_OR_NOGO"))

    def test_fetch_failure(self) -> None:
        """A failing comment fetch (status 2) is FETCH_FAIL, not an absence."""
        code, out = self.verify([{"match": "issues/7/comments", "rc": 1, "stderr": "401"}])
        self.assertEqual((code != 0, self.reason(out)), (True, "FETCH_FAIL"))

    def test_smoke_failure(self) -> None:
        """A non-zero smoke_verify is SMOKE_FAIL."""
        with mock.patch.object(ci_verify, "smoke_verify", return_value=1):
            code, out = self.verify([comments(review(HEAD), evals(HEAD))])
        self.assertEqual((code != 0, self.reason(out)), (True, "SMOKE_FAIL"))

    def test_trace_row_written(self) -> None:
        """One advisory row carries the reason code."""
        self.verify([comments(evals(HEAD))])
        rows = [json.loads(x) for x in (self.tmp / "loops/external-enforcement/trace.jsonl").read_text().splitlines()]
        self.assertEqual([(r["command"], r["reason_code"]) for r in rows], [("ci_verify.run", "REVIEW_ABSENT")])


class ReuseTests(unittest.TestCase):
    """No second implementation of the gate logic may live in ci_verify."""

    def test_functions_are_the_existing_objects(self) -> None:
        """ci_verify exposes the very same callables the merge path uses."""
        pairs = [
            (git_common, "gate_review_summary_for_pr"),
            (git_common, "gate_eval_summary_for_pr"),
            (post_evals, "smoke_verify"),
        ]
        for module, name in pairs:
            self.assertIs(getattr(ci_verify, name), getattr(module, name))

    def test_no_forked_definitions(self) -> None:
        """Source has no def of the gate functions, nor marker matching of its own."""
        source = (ROOT / "scripts/ci_verify.py").read_text()
        for name in ("gate_review_summary_for_pr", "gate_eval_summary_for_pr", "smoke_verify", "matches_marker"):
            self.assertIsNone(re.search(rf"def {name}\b", source), name)
        self.assertNotIn("coderails-review-summary", source)

    def test_template_calls_ci_verify_and_lives_outside_workflows(self) -> None:
        """The template is inert (outside .github/workflows) and calls the entrypoint."""
        template = ROOT / "docs/external-enforcement/verify.yml.template"
        self.assertIn("scripts/ci_verify.py", template.read_text())
        self.assertFalse((ROOT / ".github/workflows").exists() and any((ROOT / ".github/workflows").iterdir()))


if __name__ == "__main__":
    unittest.main()
