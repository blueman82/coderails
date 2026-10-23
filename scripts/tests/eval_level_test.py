"""Derived minimum verification level, late-freeze computation, suite integrity at PR scope, and the facts line."""

from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from hooks.scripts.tests.lib.post_evals_fixture import command, entry  # noqa: E402
from scripts.lib import eval_artifact, eval_level, eval_validation, publication_gate  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib.eval_integrity import IntegrityError, suite_hash  # noqa: E402
from scripts.lib.git_common import EvalSummary  # noqa: E402

POLICY = eval_level.load_policy()
HEAD = "c" * 40
DASHBOARD_REGEX = REPO / "skills/dashboard/app/src/lib/collect/prGates.ts"


def change(*paths: str) -> list[tuple[str, list[str]]]:
    """Diff rows (status, [paths]) as manifest_policy.parse_raw_z yields them."""
    return [("M", [p]) for p in paths]


def level_for(*paths: str, units: int = 0, declared: dict[str, object] | None = None) -> int:
    """Derived minimum level of a diff touching exactly these paths."""
    return eval_level.derive(change(*paths), units, {"facts": declared} if declared else {}, POLICY)[1]


class DeriveTests(unittest.TestCase):
    """Level 0 only for one unit with no outward surface; 1 for outward; 2 for >=3 units or irreversible."""

    def test_surfaces(self) -> None:
        """The spec's glob lists classify as documented; docs and tests are none."""
        cases = {
            "install.py": "irreversible",
            "launchd/x.plist": "irreversible",
            "scripts/integrity-gate/a.py": "irreversible",
            ".github/workflows/ci.yml": "irreversible",
            "hooks/hooks.json": "irreversible",
            "packages/codex/hooks/hooks.json": "irreversible",
            "hooks/scripts/a.py": "outward",
            "commands/x.md": "outward",
            "skills/a/SKILL.md": "outward",
            "packages/codex/skills/a/SKILL.md": "outward",
            "scripts/tests/a_test.py": "none",
            "hooks/scripts/tests/a_test.py": "none",
            "docs/RUNBOOK.md": "none",
            "README.md": "none",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(eval_level.classify(path, POLICY), expected)

    def test_levels(self) -> None:
        """The three tiers of skills/task-evals/SKILL.md lines 85-87."""
        self.assertEqual(level_for("docs/a.md"), 0)
        self.assertEqual(level_for("scripts/lib/a.py"), 1)
        self.assertEqual(level_for("install.py"), 2)
        self.assertEqual(level_for("docs/a.md", units=2), 1)
        self.assertEqual(level_for("docs/a.md", units=3), 2)

    def test_declared_facts_only_raise(self) -> None:
        """Negative control 4: declared facts below the computed ones are ignored; above them they raise."""
        low: dict[str, object] = {"work_units": 1, "surfaces": []}
        self.assertEqual(level_for("install.py", declared=low), 2)
        self.assertEqual(level_for("docs/a.md", declared={"work_units": 3, "surfaces": []}), 2)
        self.assertEqual(level_for("docs/a.md", declared={"work_units": "x", "surfaces": ["bogus"]}), 0)

    def test_docs_only_is_not_forced_up(self) -> None:
        """Negative control 5: a docs-and-tests change stays at level 0."""
        self.assertEqual(level_for("docs/a.md", "scripts/tests/a_test.py", "README.md"), 0)

    def test_renames_count_both_sides(self) -> None:
        """A rename out of an irreversible path still touches it."""
        rows = [("R100", ["install.py", "docs/old-install.md"])]
        self.assertEqual(eval_level.derive(rows, 0, {}, POLICY)[1], 2)


class RepoCase(unittest.TestCase):
    """A real temp repository: base commit on main, origin/main ref, feature branch."""

    def git(self, *args: str) -> str:
        """Run Git in the temp repo with a fixed identity."""
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"}
        env |= {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        done = subprocess.run(["git", *args], cwd=self.dir, env=env, check=True, capture_output=True, text=True)
        return done.stdout.strip()

    def setUp(self) -> None:
        """Commit a base, publish it as origin/main, then branch."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.git("init", "-q", "-b", "main")
        (self.dir / "README.md").write_text("base\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("checkout", "-qb", "feature/x")
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)

    def commit(self, name: str) -> str:
        """Commit one new file on the feature branch and return the commit."""
        (self.dir / name).parent.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_text(name)
        self.git("add", "-A")
        self.git("commit", "-qm", name)
        return self.git("rev-parse", "HEAD")

    def posted(
        self, level: int, head: str, derived: int | None = None, late: bool = False, **over: object
    ) -> tuple[EvalSummary, dict[str, object]]:
        """The newest trusted artifact as post would have written it (marker level, facts line, embed)."""
        data: dict[str, object] = {
            "verification_level": level, "head_sha": head or self.git("rev-parse", "HEAD"),
            "task_ref": "1", "evals": [entry()], **over,
        }  # fmt: skip
        data.setdefault("frozen_sha", self.base)
        data["frozen_hash"] = suite_hash(data)
        digest = suite_hash(data)
        stamp = eval_artifact.facts_line(level if derived is None else derived, late, digest[:16])
        return EvalSummary(0, str(level), json.dumps(data), facts=stamp), data


class LateFreezeTests(RepoCase):
    """late_freeze is computed from ancestry, not only tolerated when disclosed."""

    def test_ancestor_of_base_is_not_late(self) -> None:
        """A freeze at (or before) the branch base is on time."""
        self.assertFalse(eval_level.late_freeze(self.base, self.base))

    def test_freeze_on_the_branch_is_late(self) -> None:
        """Negative control: a freeze commit made after branching is late."""
        later = self.commit("a.txt")
        self.assertTrue(eval_level.late_freeze(later, self.base))

    def test_blank_or_unknown_sha(self) -> None:
        """No frozen_sha and an unresolvable one are late (cannot be shown to precede the base)."""
        self.assertTrue(eval_level.late_freeze("", self.base))
        self.assertTrue(eval_level.late_freeze("f" * 40, self.base))

    def test_branch_base_and_pr_changes(self) -> None:
        """The base is the merge-base with origin/main; changes are the diff from it."""
        head = self.commit("install.py")
        self.assertEqual(eval_level.branch_base(head), self.base)
        self.assertEqual(eval_level.pr_changes("", head), [("A", ["install.py"])])

    def test_validate_freeze_still_requires_disclosure(self) -> None:
        """The refactor keeps validate_freeze's behaviour: late and undisclosed is refused, disclosed accepted."""
        later = self.commit("a.txt")
        path = self.dir / "evals.json"
        path.write_text(json.dumps({"frozen_sha": later, "verification_justification": "x"}))
        with self.assertRaisesRegex(ValueError, "disclose the late freeze"):
            eval_validation.validate_freeze(path)
        path.write_text(json.dumps({"frozen_sha": later, "verification_justification": "late freeze: see PR"}))
        eval_validation.validate_freeze(path)


class SuiteIntegrityTests(unittest.TestCase):
    """verify_suite and frozen_hash are enforced by the level check, not only at grade time."""

    def frozen(self, level: int = 1) -> dict[str, object]:
        """A suite stamped like smoke-run does."""
        data: dict[str, object] = {
            "verification_level": level, "task_ref": "1", "evals": [entry()], "frozen_sha": "a" * 40,
        }  # fmt: skip
        data["frozen_hash"] = suite_hash(data)
        return data

    def test_untouched_suite_passes(self) -> None:
        """Negative control 3: restoring the untouched suite passes."""
        eval_level.check_suite(self.frozen(), "1")

    def test_edited_cmd_is_a_hash_mismatch(self) -> None:
        """An oracle edit without amend: suite_hash_mismatch."""
        data = self.frozen()
        data["evals"][0]["cmd"] = command("print('weaker')")  # type: ignore[index]
        with self.assertRaises(IntegrityError) as caught:
            eval_level.check_suite(data, "1")
        self.assertEqual(caught.exception.code, "suite_hash_mismatch")

    def test_stripped_hash_is_not_frozen(self) -> None:
        """A level >=1 suite with no frozen_hash is not_frozen; level 0 needs none."""
        data = self.frozen()
        del data["frozen_hash"]
        with self.assertRaises(IntegrityError) as caught:
            eval_level.check_suite(data, "1")
        self.assertEqual(caught.exception.code, "not_frozen")
        eval_level.check_suite(data, "0")

    def test_stripped_hash_of_a_graded_suite(self) -> None:
        """Deleting frozen_hash from a suite that carries a verified grading is integrity_stripped."""
        data = self.frozen()
        del data["frozen_hash"]
        data["grading"] = {"integrity": "verified"}
        with self.assertRaises(IntegrityError) as caught:
            eval_level.check_suite(data, "1")
        self.assertEqual(caught.exception.code, "integrity_stripped")

    def test_amendment_via_chain_is_accepted(self) -> None:
        """An oracle edit recorded with append_amendment keeps the suite verified."""
        from scripts.lib.eval_integrity import append_amendment

        data = self.frozen()
        data["evals"][0]["cmd"] = command("print('reason')")  # type: ignore[index]
        append_amendment(data, "E1", "tighten", "me")
        eval_level.check_suite(data, "1")


class FactsLineTests(unittest.TestCase):
    """Line 2 of the body: render/parse round trip and the compat contract of line 1."""

    def test_round_trip(self) -> None:
        """Render then parse returns the facts; malformed lines parse to None."""
        line = eval_artifact.facts_line(2, True, "ab" * 8)
        expected = "<!-- coderails-eval-facts v1 derived_min_level=2 late_freeze=1 suite=" + "ab" * 8 + " -->"
        self.assertEqual(line, expected)
        self.assertEqual(eval_artifact.parse_facts(line), (2, True, "ab" * 8))
        for bad in ("", line.replace("late_freeze=1", "late_freeze=2"), line.replace("v1", "v2"), line + " x"):
            self.assertIsNone(eval_artifact.parse_facts(bad))

    def test_first_line_is_the_unchanged_v1_marker(self) -> None:
        """Compat: line 1 is byte-identical to the old marker and matches the dashboard regex and the daemon prefix."""
        marker = eval_artifact.marker("12", HEAD, "GO", "1")
        self.assertEqual(
            marker, f"<!-- coderails-eval-summary v1 pr=12 head_sha={HEAD} result=GO verification_level=1 -->"
        )
        source = DASHBOARD_REGEX.read_text()
        self.assertIn("coderails-eval-summary ${escapedVersion} pr=(\\\\S+) head_sha=(\\\\S+) result=", source)
        dashboard = (
            r"^<!-- coderails-eval-summary v1 pr=(\S+) head_sha=(\S+) result=(GO|NO-GO) "
            r"verification_level=([0-2]) -->$"
        )
        self.assertRegex(marker, dashboard)
        daemon_prefix = f"<!-- coderails-eval-summary v1 pr=12 head_sha={HEAD} "  # integrity_policy.gate_pr
        self.assertTrue(marker.startswith(daemon_prefix) and marker.endswith(" -->"))
        self.assertTrue(eval_artifact.matches_marker(marker, "12", HEAD))
        # the facts line is a different comment kind: it must never parse as a marker
        self.assertFalse(re.match(dashboard, eval_artifact.facts_line(1, False, "0" * 16)))

    def test_declared_vs_deepcopy_isolated(self) -> None:
        """Derive does not mutate its inputs."""
        declared = {"facts": {"work_units": 3, "surfaces": ["outward"]}}
        before = copy.deepcopy(declared)
        eval_level.derive(change("docs/a.md"), 0, declared, POLICY)
        self.assertEqual(declared, before)


class MergeCheckTests(RepoCase):
    """publication_gate.eval_level_check recomputes the level, late freeze and suite integrity from the live PR."""

    def check(self, summary: EvalSummary, progress: str = "") -> list[str]:
        """Codes the eval_level check returns for this summary on the current branch head."""
        head = self.git("rev-parse", "HEAD")
        with (
            mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
            mock.patch.object(git, "pr_field", return_value=self.base),
        ):
            return [v["code"] for v in publication_gate.eval_level_check("7", head, "", progress)]

    def test_registered_last(self) -> None:
        """The check is appended to CHECKS, so merge.py, the Claude direct arm and the Codex hook all run it."""
        self.assertEqual(publication_gate.CHECKS[-1].__name__, "eval_level_check")

    def test_install_py_levels(self) -> None:
        """Acceptance 1 and control 1: install.py at level 0 and 1 is refused, at level 2 it passes."""
        self.commit("install.py")
        for level in (0, 1):
            self.assertIn("level_below_derived", self.check(self.posted(level, "")[0]))
        self.assertEqual(self.check(self.posted(2, "")[0]), [])

    def test_docs_only_at_level_zero(self) -> None:
        """Negative control 5: a docs-only PR at level 0 is accepted."""
        self.commit("docs/a.md")
        self.assertEqual(self.check(self.posted(0, "")[0]), [])

    def test_three_units_at_level_one(self) -> None:
        """Acceptance 1: declared (or progress) work_units >= 3 at level 1 is refused; the stamp cannot lower it."""
        self.commit("docs/a.md")
        summary, _ = self.posted(1, "", derived=1, facts={"work_units": 3, "surfaces": []})
        self.assertIn("level_below_derived", self.check(summary))
        progress = self.dir / "p.json"
        progress.write_text(json.dumps({"work_units": {"1": {}, "2": {}, "3": {}}}))
        self.assertIn("level_below_derived", self.check(self.posted(1, "")[0], str(progress)))

    def test_oracle_edit_after_posting(self) -> None:
        """Acceptance 2: an embed whose cmd differs from the freeze is suite_hash_mismatch (and the marker differs)."""
        self.commit("install.py")
        summary, _ = self.posted(2, "")
        edited = json.loads(summary.embed)
        edited["evals"][0]["cmd"] = command("print('weaker')")
        codes = self.check(EvalSummary(0, "2", json.dumps(edited), facts=summary.facts))
        self.assertIn("suite_hash_mismatch", codes)
        self.assertIn("suite_hash_marker_mismatch", codes)

    def test_stripped_frozen_hash(self) -> None:
        """Acceptance 2: a level >= 1 embed without frozen_hash is not_frozen."""
        self.commit("install.py")
        summary, _ = self.posted(2, "")
        stripped = json.loads(summary.embed)
        del stripped["frozen_hash"]
        self.assertIn("not_frozen", self.check(EvalSummary(0, "2", json.dumps(stripped), facts=summary.facts)))

    def test_late_freeze_must_be_stamped(self) -> None:
        """Acceptance 3: a branch frozen_sha with a facts line claiming late_freeze=0 is late_freeze_unstamped."""
        late = self.commit("install.py")
        self.assertIn("late_freeze_unstamped", self.check(self.posted(2, "", frozen_sha=late)[0]))
        self.assertEqual(self.check(self.posted(2, "", late=True, frozen_sha=late)[0]), [])
        self.assertIn("late_freeze_unstamped", self.check(self.posted(2, "", late=True)[0]))  # claims late, is not

    def test_missing_facts_line(self) -> None:
        """A v1 artifact with no facts line is refused when the diff needs level >= 1, accepted for docs."""
        self.commit("install.py")
        summary, _ = self.posted(2, "")
        self.assertIn("eval_facts_missing", self.check(EvalSummary(0, "2", summary.embed)))
        self.git("reset", "-q", "--hard", self.base)
        self.commit("docs/a.md")
        summary, _ = self.posted(0, "")
        self.assertEqual(self.check(EvalSummary(0, "0", summary.embed)), [])

    def test_absent_and_unreadable_artifacts(self) -> None:
        """No GO artifact and a failed fetch are refusals, never passes."""
        self.commit("docs/a.md")
        self.assertEqual(self.check(EvalSummary(1)), ["eval_artifact_missing"])
        self.assertEqual(self.check(EvalSummary(2, failure_reason="comments")), ["eval_artifact_unreadable"])
        self.assertEqual(self.check(EvalSummary(0, "0", "not json")), ["eval_embed_malformed"])


class PathTests(RepoCase):
    """The same check is reached from merge.py (enforce) and from the Claude direct-merge path (merge_reason)."""

    def test_merge_py_and_claude_direct_path_refuse(self) -> None:
        """Acceptance 1: install.py at level 0 is refused with the code first on both paths; level 2 is not."""
        from hooks.scripts.lib import pr_merge_gate

        head = self.commit("install.py")
        for level, refused in ((0, True), (2, False)):
            summary = self.posted(level, "")[0]
            with (
                self.subTest(level=level),
                mock.patch.object(publication_gate, "CHECKS", [publication_gate.eval_level_check]),
                mock.patch.object(git, "gate_eval_summary_for_pr", return_value=summary),
                mock.patch.object(git, "pr_field", return_value=self.base),
                mock.patch.object(pr_merge_gate, "gate_eval_summary_for_pr", return_value=summary),
                mock.patch.object(pr_merge_gate, "pr_field", return_value=head),
                mock.patch.object(pr_merge_gate, "smoke_verify", return_value=0),
                mock.patch.object(pr_merge_gate, "integrity_reason", return_value=""),
            ):
                reason = pr_merge_gate.merge_reason("7", str(self.dir))
                if refused:
                    self.assertTrue(reason.startswith("level_below_derived"), reason)
                    self.assertIn("post_evals.py post", reason)
                    with self.assertRaises(git.WorkflowError) as caught:
                        publication_gate.enforce("7", head)
                    self.assertTrue(str(caught.exception).startswith("level_below_derived"))
                else:
                    self.assertEqual(reason, "")
                    publication_gate.enforce("7", head)


class PolicyDriftTests(unittest.TestCase):
    """The mirrored policy and its documented constant."""

    def test_constant_matches_task_evals_skill(self) -> None:
        """Level 2 at three work units is the skills/task-evals rule, encoded once."""
        self.assertEqual(POLICY["level_2_work_units"], 3)
        self.assertIn("≥3 work-units", (REPO / "skills/task-evals/SKILL.md").read_text())

    def test_unreadable_policy_raises(self) -> None:
        """A missing or ill-shaped policy fails closed with a coded ValueError."""
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "p.json"
            bad.write_text("{")
            with self.assertRaisesRegex(ValueError, "surface_policy_unreadable"):
                eval_level.load_policy(bad)
            bad.write_text('{"none": [], "irreversible": "x", "outward": [], "level_2_work_units": 3}')
            with self.assertRaisesRegex(ValueError, "surface_policy_unreadable"):
                eval_level.load_policy(bad)


if __name__ == "__main__":
    unittest.main()
