"""The publication command binds a registered unit, state path, worktree and staged manifest."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from hooks.scripts.tests.workflow_push_fixture import PushFixture


class PushUnitBindingTests(unittest.TestCase):
    """Use an isolated local bare origin; invalid bindings cannot commit or push."""

    def test_unit_flags_reject_foreign_unit_worktree_and_manifest(self) -> None:
        """Every refusal occurs before the source commit and transport."""
        for defect in ("unit", "worktree", "manifest"):
            with self.subTest(defect), tempfile.TemporaryDirectory() as scratch:
                fixture = PushFixture(Path(scratch))
                progress = fixture.root / "progress.json"
                entry = {"manifest": ["base.txt"], "worktree": str(fixture.repo)}
                if defect == "worktree":
                    entry["worktree"] = str(fixture.root / "foreign")
                if defect == "manifest":
                    entry["manifest"] = ["src/**"]
                progress.write_text(json.dumps({"work_units": {"1": entry}}))
                (fixture.repo / "base.txt").write_text("changed")
                before = fixture.git(fixture.repo, "rev-parse", "HEAD")
                result = fixture.push("--unit", "2" if defect == "unit" else "1", "--progress", str(progress))
                self.assertNotEqual(result.returncode, 0, (defect, result.stdout, result.stderr))
                self.assertEqual(fixture.git(fixture.repo, "rev-parse", "HEAD"), before)

    def test_valid_unit_flags_publish_the_scoped_change(self) -> None:
        """A registered unit in its assigned checkout can use the exact command."""
        with tempfile.TemporaryDirectory() as scratch:
            fixture = PushFixture(Path(scratch))
            progress = fixture.root / "progress.json"
            progress.write_text(
                json.dumps({"work_units": {"1": {"manifest": ["base.txt"], "worktree": str(fixture.repo)}}})
            )
            (fixture.repo / "base.txt").write_text("changed")
            result = fixture.push("--unit", "1", "--progress", str(progress))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                fixture.git(fixture.repo, "rev-parse", "HEAD"), fixture.git(fixture.repo, "rev-parse", "origin/feature")
            )

    def test_owned_graph_push_passes_unit_to_the_global_gate(self) -> None:
        """An active graph unit can publish only with its exact unit and progress flags."""
        with tempfile.TemporaryDirectory() as scratch:
            fixture = PushFixture(Path(scratch))
            progress = fixture.root / "graphs/loop/S1/progress.json"
            progress.parent.mkdir(parents=True)
            progress.write_text(
                json.dumps(
                    {
                        "session_id": "S1",
                        "loop_id": "L1",
                        "graph": {"nodes": {}},
                        "work_units": {"1": {"manifest": ["base.txt"], "worktree": str(fixture.repo)}},
                    }
                )
            )
            (fixture.repo / "base.txt").write_text("changed")
            env = dict(
                fixture.environment,
                CLAUDE_AGENTIC_LOOP_DIR=str(fixture.root / "graphs"),
                CODERAILS_PUBLICATION_SESSION_ID="S1",
            )
            script = Path(__file__).resolve().parents[3] / "scripts/push.py"
            without = subprocess.run(
                [sys.executable, str(script)], cwd=fixture.repo, env=env, capture_output=True, text=True
            )
            self.assertIn("graph unit requires --unit and --progress", without.stderr)
            with_flags = subprocess.run(
                [sys.executable, str(script), "--unit", "1", "--progress", str(progress)],
                cwd=fixture.repo,
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(with_flags.returncode, 0, with_flags.stdout + with_flags.stderr)

    def test_prior_out_of_manifest_commit_cannot_be_published(self) -> None:
        """A clean index cannot hide an earlier unscoped commit from the push."""
        with tempfile.TemporaryDirectory() as scratch:
            fixture = PushFixture(Path(scratch))
            progress = fixture.root / "progress.json"
            progress.write_text(
                json.dumps({"work_units": {"1": {"manifest": ["base.txt"], "worktree": str(fixture.repo)}}})
            )
            (fixture.repo / "outside.txt").write_text("foreign")
            fixture.git(fixture.repo, "add", "outside.txt")
            fixture.git(fixture.repo, "commit", "-m", "preexisting foreign commit")
            fixture.record_pushes()
            result = fixture.push("--unit", "1", "--progress", str(progress))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                fixture.git(fixture.repo, "rev-parse", "origin/main"), fixture.git(fixture.repo, "rev-parse", "main")
            )
            self.assertFalse(fixture.log.exists(), result.stdout + result.stderr)

    def test_first_stacked_push_uses_recorded_base(self) -> None:
        """An unpublished child excludes its parent unit from the scoped diff."""
        with tempfile.TemporaryDirectory() as scratch:
            fixture = PushFixture(Path(scratch))
            fixture.git(fixture.repo, "checkout", "-b", "parent")
            (fixture.repo / "parent.txt").write_text("parent unit")
            fixture.git(fixture.repo, "add", "parent.txt")
            fixture.git(fixture.repo, "commit", "-m", "parent unit")
            fixture.git(fixture.repo, "push", "-u", "origin", "parent")
            fixture.git(fixture.repo, "checkout", "-b", "child")
            pr_log = fixture.root / "pr-create.txt"
            fixture.stub(
                "gh",
                "import sys\nfrom pathlib import Path\n"
                "if sys.argv[1:3] == ['pr', 'create']:\n"
                f"    Path({str(pr_log)!r}).write_text(' '.join(sys.argv[1:]))\n"
                "    print('https://github.com/fixture/repo/pull/1')\n",
            )
            progress = fixture.root / "progress.json"
            progress.write_text(json.dumps({"work_units": {"2": {"manifest": ["child.txt"], "base_branch": "parent"}}}))
            (fixture.repo / "child.txt").write_text("child unit")
            result = fixture.push("--unit", "2", "--progress", str(progress), "--add", "child.txt")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                fixture.git(fixture.repo, "rev-parse", "HEAD"), fixture.git(fixture.repo, "rev-parse", "origin/child")
            )
            self.assertIn("-B parent", pr_log.read_text())

    def test_out_of_manifest_rename_source_cannot_be_published(self) -> None:
        """The origin of a rename is part of the unit's publication scope."""
        with tempfile.TemporaryDirectory() as scratch:
            fixture = PushFixture(Path(scratch))
            fixture.git(fixture.repo, "checkout", "main")
            (fixture.repo / "outside.txt").write_text("outside")
            fixture.git(fixture.repo, "add", "outside.txt")
            fixture.git(fixture.repo, "commit", "-m", "add source")
            fixture.git(fixture.repo, "push", "origin", "main")
            fixture.git(fixture.repo, "checkout", "feature")
            fixture.git(fixture.repo, "merge", "main")
            (fixture.repo / "scope").mkdir()
            fixture.git(fixture.repo, "mv", "outside.txt", "scope/inside.txt")
            fixture.git(fixture.repo, "commit", "-m", "rename into unit")
            progress = fixture.root / "progress.json"
            progress.write_text(json.dumps({"work_units": {"1": {"manifest": ["scope/**"]}}}))
            fixture.record_pushes()
            result = fixture.push("--unit", "1", "--progress", str(progress))
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertFalse(fixture.log.exists(), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
