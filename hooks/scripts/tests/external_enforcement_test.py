"""external_enforcement plan/apply with a fake gh: dry-run default, refusals, and stable reason codes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests import fake_gh_support as fake

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/external_enforcement.py"
RULESET = json.loads((ROOT / "docs/external-enforcement/ruleset.json").read_text())
LIST = "api repos/blueman82/coderails/rulesets"
SEEN = [
    {"match": "commits?per_page", "stdout": "abc123\n"},
    {"match": "commits/abc123/check-runs", "stdout": "verify\n"},
    {"match": "commits/abc123/statuses", "stdout": ""},
]
UNSEEN = [
    {"match": "commits?per_page", "stdout": "abc123\n"},
    {"match": "commits/abc123/check-runs", "stdout": "lint\n"},
    {"match": "commits/abc123/statuses", "stdout": ""},
]


class EnforcementTests(unittest.TestCase):
    """Drive the CLI as a subprocess so the real argv, exit code and stdout contract are exercised."""

    def setUp(self) -> None:
        """Isolated enforcement root (ruleset + template), trace dir and fake-gh directory."""
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.root = self.tmp / "root"
        (self.root / "docs/external-enforcement").mkdir(parents=True)
        shutil.copy(ROOT / "docs/external-enforcement/ruleset.json", self.root / "docs/external-enforcement")
        (self.root / "docs/external-enforcement/verify.yml.template").write_text("name: verify\n")

    def run_cli(
        self, routes: list[dict[str, Any]], *args: str
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        """Run the script with the fake gh on PATH; return the process and the env for call inspection."""
        env = {**os.environ, **fake.install(self.tmp, routes), "CLAUDE_AGENTIC_LOOP_DIR": str(self.tmp / "loops")}
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            cwd=ROOT,
            env=env,
            check=False,
        )
        return proc, env

    def test_plan_empty_list_is_dry_run_and_read_only(self) -> None:
        """An empty live list yields a diff, DRY_RUN, and no write call."""
        proc, env = self.run_cli([{"match": LIST, "stdout": "[]"}], "plan")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("REASON=DRY_RUN", proc.stdout)
        self.assertIn("coderails-main-protection", proc.stdout)
        self.assertFalse([c for c in fake.calls(env) if "-X" in c["argv"]])

    def test_plan_matching_live_ruleset_is_no_diff(self) -> None:
        """A live ruleset covering the definition (extra server keys ignored) is NO_DIFF."""
        live = {**RULESET, "id": 9, "source": "blueman82/coderails"}
        routes = [
            {"match": "rulesets/9", "stdout": json.dumps(live)},
            {"match": LIST, "stdout": json.dumps([{"id": 9, "name": RULESET["name"]}])},
        ]
        proc, _ = self.run_cli(routes, "plan")
        self.assertIn("REASON=NO_DIFF", proc.stdout)

    def test_plan_gh_failure(self) -> None:
        """A failing gh is GH_FAIL with a non-zero exit."""
        proc, _ = self.run_cli([{"match": LIST, "rc": 1, "stderr": "boom"}], "plan")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("REASON=GH_FAIL", proc.stdout)

    def test_apply_without_yes_refuses(self) -> None:
        """No --yes means NO_YES and no gh write, even when everything else is fine."""
        proc, env = self.run_cli([{"match": LIST, "stdout": "[]"}, *SEEN], "apply")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("REASON=NO_YES", proc.stdout)
        self.assertFalse([c for c in fake.calls(env) if "-X" in c["argv"]])

    def test_apply_template_missing(self) -> None:
        """Without the workflow template there is nothing that can post the check."""
        (self.root / "docs/external-enforcement/verify.yml.template").unlink()
        proc, _ = self.run_cli([{"match": LIST, "stdout": "[]"}, *SEEN], "apply", "--yes")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("REASON=TEMPLATE_MISSING", proc.stdout)

    def test_apply_check_never_seen_refuses(self) -> None:
        """An unobserved verify check would lock every merge, so apply refuses."""
        proc, env = self.run_cli([{"match": LIST, "stdout": "[]"}, *UNSEEN], "apply", "--yes")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("REASON=CHECK_NEVER_SEEN", proc.stdout)
        self.assertFalse([c for c in fake.calls(env) if "-X" in c["argv"]])

    def test_apply_creates_when_check_seen(self) -> None:
        """Seen check plus --yes POSTs the exact definition and reports APPLIED."""
        routes = [{"match": "-X POST", "stdout": "{}"}, {"match": LIST, "stdout": "[]"}, *SEEN]
        proc, env = self.run_cli(routes, "apply", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("REASON=APPLIED", proc.stdout)
        posts = [c for c in fake.calls(env) if "POST" in c["argv"]]
        self.assertEqual(len(posts), 1)
        self.assertEqual(json.loads(str(posts[0]["stdin"])), RULESET)

    def test_apply_updates_existing_with_put(self) -> None:
        """A drifted live ruleset is replaced with PUT on its id."""
        drifted = {**RULESET, "id": 9, "enforcement": "disabled"}
        routes = [
            {"match": "-X PUT", "stdout": "{}"},
            {"match": "rulesets/9", "stdout": json.dumps(drifted)},
            {"match": LIST, "stdout": json.dumps([{"id": 9, "name": RULESET["name"]}])},
            *SEEN,
        ]
        proc, env = self.run_cli(routes, "apply", "--yes")
        self.assertIn("REASON=APPLIED", proc.stdout)
        self.assertTrue([c for c in fake.calls(env) if "PUT" in c["argv"]])

    def test_trace_row_is_written_fail_open(self) -> None:
        """Each invocation appends one advisory trace row carrying its reason code."""
        self.run_cli([{"match": LIST, "stdout": "[]"}], "plan")
        rows = [json.loads(x) for x in (self.tmp / "loops/external-enforcement/trace.jsonl").read_text().splitlines()]
        self.assertEqual([(r["command"], r["reason_code"]) for r in rows], [("external_enforcement.plan", "DRY_RUN")])
        self.assertTrue(rows[0]["event_id"])


if __name__ == "__main__":
    unittest.main()
