"""The single publication gate: evaluate/enforce, the merge.py and push.py call sites, and headless subprocess runs."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import merge  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_policy, publication_gate  # noqa: E402
from scripts.tests.manifest_policy_test import RepoCase, git_cmd  # noqa: E402

SECRET = ".en" + "v"  # two parts so no source line spells the secret-file name
GH_SHIM = """#!/bin/sh
case "$1 $2" in
  "pr view")
    case "$5" in
      headRefOid) echo "$FAKE_SHA" ;;
      baseRefOid) echo "$BASE_SHA" ;;
      state) echo OPEN ;;
      title) echo fixture ;;
      headRefName) echo main ;;
    esac ;;
  "pr merge") echo merged >> "$FAKE_GH_LOG" ;;
  "pr create") echo https://github.com/o/r/pull/9 ;;
  api) exit 1 ;;
esac
exit 0
"""
MERGE_DRIVER = (
    "import sys; sys.path.insert(0, %r)\n"
    "from scripts import merge\n"
    "merge.verify_gates = lambda number: merge.git.pr_field(number, 'headRefOid')\n"
    "from scripts.lib import git_common\n"
    "git_common.review_passes_for_pr = lambda number, sha: git_common.ReviewPasses(0, ())  # manifest under test\n"
    "git_common.gate_eval_summary_for_pr = lambda number, sha: git_common.EvalSummary(\n"
    '    0, \'0\', \'{"verification_level": 0, "task_ref": "1", "evals": []}\')  # eval level has its own tests\n'
    "merge.cleanup = lambda number, default: None\n"
    "raise SystemExit(merge.main(['7']))\n"
)


def install_gh_shim(directory: Path) -> Path:
    """Write an executable fake gh into directory/bin and return that bin directory."""
    bin_dir = directory / "bin"
    bin_dir.mkdir(exist_ok=True)
    shim = bin_dir / "gh"
    shim.write_text(GH_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return bin_dir


def fixed_check(found: list[dict[str, str]], calls: list[str] | None = None, name: str = "") -> publication_gate.Check:
    """A check returning found, recording its name in calls when given."""

    def check(number: str, sha: str, unit: str, progress: str) -> list[dict[str, str]]:
        if calls is not None:
            calls.append(name)
        return found

    return check


class EvaluateTests(unittest.TestCase):
    """evaluate collects check results; enforce raises with the reason code first."""

    def test_violation_shape_and_enforce_text(self) -> None:
        """A registered check's violations come back as {code, detail}; enforce text starts with the code."""
        found = [{"code": "diff_manifest:denied_path", "detail": "k"}]
        with mock.patch.object(publication_gate, "CHECKS", [fixed_check(found)]):
            self.assertEqual(publication_gate.evaluate("7", "abc"), found)
            with self.assertRaises(git.WorkflowError) as caught:
                publication_gate.enforce("7", "abc")
        self.assertTrue(str(caught.exception).startswith("diff_manifest:denied_path"))

    def test_clean_checks_do_not_raise(self) -> None:
        """Negative control: no violations means no exception."""
        with mock.patch.object(publication_gate, "CHECKS", [fixed_check([])]):
            self.assertEqual(publication_gate.evaluate("7", "abc"), [])
            publication_gate.enforce("7", "abc")

    def test_later_units_append_checks(self) -> None:
        """A second appended check runs after the first, so U2 and U3 only append."""
        calls: list[str] = []
        checks = [fixed_check([], calls, "a"), fixed_check([{"code": "x", "detail": ""}], calls, "b")]
        with mock.patch.object(publication_gate, "CHECKS", checks):
            self.assertEqual(publication_gate.evaluate("7", "abc"), [{"code": "x", "detail": ""}])
        self.assertEqual(calls, ["a", "b"])

    def test_manifest_is_registered_first(self) -> None:
        """U1 registers the manifest check."""
        self.assertEqual(publication_gate.CHECKS[0].__name__, "manifest_check")

    def test_metadata_error_obeys_mode_and_keeps_the_manifest_reason(self) -> None:
        """Repository metadata errors refuse under enforce and fail open under advisory."""
        for mode, expected in (("enforce", ["diff_manifest:manifest_internal_error"]), ("advisory", [])):
            with (
                self.subTest(mode=mode),
                mock.patch.object(publication_gate, "CHECKS", [publication_gate.manifest_check]),
                mock.patch.object(manifest_policy, "settings", return_value=(mode, "policy.json", False)),
                mock.patch.object(git, "repo", side_effect=RuntimeError("metadata failure")),
            ):
                self.assertEqual([v["code"] for v in publication_gate.evaluate("7", "head")], expected)


class MergeCallTests(unittest.TestCase):
    """merge.py calls publication_gate.enforce after verify_gates and before gh pr merge."""

    def run_merge(self, effect: Exception | None, arguments: list[str] | None = None) -> tuple[int, list[str]]:
        """Run merge.main for PR 7 with the evidence gates stubbed; return status and the call order."""
        order: list[str] = []

        def fake_run(*argv: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            if argv[:3] == ("gh", "pr", "merge"):
                order.append("merge")
            return subprocess.CompletedProcess(argv, 0, "", "")

        def field(number: str, name: str, fallback: str = "") -> str:
            return {"state": "OPEN", "headRefOid": "sha7"}.get(name, fallback)

        def publication(*args: str, **kwargs: str) -> None:
            order.append("publication")
            if effect:
                raise effect

        def evidence(number: str) -> str:
            order.append("evidence")
            return "sha7"

        with (
            mock.patch.object(merge, "verify_gates", side_effect=evidence),
            mock.patch.object(git, "require_repo"),
            mock.patch.object(git, "main", return_value="main"),
            mock.patch.object(git, "pr_field", side_effect=field),
            mock.patch.object(git, "protected", return_value=False),
            mock.patch.object(git, "run", side_effect=fake_run),
            mock.patch.object(merge, "cleanup"),
            mock.patch.object(publication_gate, "enforce", side_effect=publication),
        ):
            status = merge.main(["7"] if arguments is None else arguments)
        return status, order

    def test_order_and_pass(self) -> None:
        """Evidence gates, then the publication gate, then the remote merge."""
        self.assertEqual(self.run_merge(None), (0, ["evidence", "publication", "merge"]))

    def test_gh_repo_override_refuses_before_lookup(self) -> None:
        """Direct merge.py cannot resolve local evidence for a GH_REPO-retargeted remote merge."""
        with mock.patch.dict(os.environ, {"GH_REPO": "other/repo"}):
            self.assertEqual(self.run_merge(None), (1, []))

    def test_refusal_blocks_merge(self) -> None:
        """A refusing publication gate returns 1 and never reaches gh pr merge."""
        status, order = self.run_merge(git.WorkflowError("diff_manifest:denied_path"))
        self.assertEqual((status, "merge" in order), (1, False))

    def test_ambiguous_cli_target_never_reaches_a_merge(self) -> None:
        """A second positional target must refuse rather than silently selecting the first."""
        self.assertEqual(self.run_merge(None, ["7", "9"]), (1, []))

    def test_unit_and_progress_are_forwarded(self) -> None:
        """--unit N --progress PATH reach the gate."""

        def field(number: str, name: str, fallback: str = "") -> str:
            return "OPEN" if name == "state" else "sha7"

        with (
            mock.patch.object(merge, "verify_gates", return_value="sha7"),
            mock.patch.object(git, "require_repo"),
            mock.patch.object(git, "main", return_value="main"),
            mock.patch.object(git, "pr_field", side_effect=field),
            mock.patch.object(git, "protected", return_value=False),
            mock.patch.object(git, "run", return_value=subprocess.CompletedProcess([], 0, "", "")),
            mock.patch.object(merge, "cleanup"),
            mock.patch.object(publication_gate, "enforce") as enforce,
        ):
            merge.main(["7", "--unit", "2", "--progress", "/p.json"])
        enforce.assert_called_once_with("7", "sha7", unit="2", progress="/p.json")


class HeadlessTests(RepoCase):
    """The real scripts as subprocesses: no hooks, headless env, fake gh on PATH, real git in a temp repo."""

    def setUp(self) -> None:
        """Make origin a GitHub-looking remote with a local bare push target and a gh shim."""
        super().setUp()
        bare = self.dir.parent / "bare.git"
        git_cmd(self.dir.parent, "init", "-q", "--bare", str(bare))
        git_cmd(self.dir, "remote", "add", "origin", "https://github.com/o/r.git")
        git_cmd(self.dir, "config", "remote.origin.pushurl", str(bare))
        git_cmd(self.dir, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.ghlog = self.dir.parent / "gh.log"
        self.env = {
            **os.environ,
            "PATH": f"{install_gh_shim(self.dir.parent)}{os.pathsep}{os.environ['PATH']}",
            "CODERAILS_HEADLESS_RUN": "1",
            "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop),
            "FAKE_GH_LOG": str(self.ghlog),
            "FAKE_SHA": "",
            "BASE_SHA": git_cmd(self.dir, "rev-parse", "origin/main").strip(),
        }
        self.env.pop("CLAUDE_CODE_SESSION_ID", None)

    def commit_secret(self) -> str:
        """Commit a secret-shaped file and return the head sha."""
        (self.dir / SECRET).write_text("k=v\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "secret")
        return git_cmd(self.dir, "rev-parse", "HEAD").strip()

    def config(self, text: str) -> None:
        """Write the repo's workflow config."""
        (self.dir / ".coderails").mkdir(exist_ok=True)
        (self.dir / ".coderails/workflow.config.yaml").write_text(text)

    def rows(self) -> list[str]:
        """Return command/outcome/reason triples from every trace file."""
        lines = [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]
        return [f"{r['command']}/{r['outcome']}/{r['reason_code']}" for r in lines]

    def merge(self, sha: str) -> subprocess.CompletedProcess[str]:
        """Run merge.main for PR 7 in a subprocess with the evidence gates stubbed."""
        env = {**self.env, "FAKE_SHA": sha}
        code = MERGE_DRIVER % str(REPO)
        return subprocess.run([sys.executable, "-c", code], cwd=self.dir, env=env, capture_output=True, text=True)

    def test_merge_refused_without_any_config(self) -> None:
        """Headless merge of an out-of-policy diff exits non-zero and writes the refused trace rows."""
        result = self.merge(self.commit_secret())
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("diff_manifest:denied_path", result.stderr)
        self.assertFalse(self.ghlog.exists(), "gh pr merge must not run")
        self.assertIn("diff-manifest/refused/denied_path", self.rows())
        self.assertIn("publication/refused/diff_manifest:denied_path", self.rows())

    def test_merge_off_control_merges(self) -> None:
        """Negative control: diff_manifest off lets the same diff reach gh pr merge.

        The config file is itself a committed control file (.coderails/** needs security-review), so the review
        check and the eval-level check (the stubbed level-0 artifact is below the derived level of those paths) are
        switched off too; this test is about the manifest only.
        """
        self.config("diff_manifest: off\nreview_passes: off\neval_level: off\n")
        result = self.merge(self.commit_secret())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.ghlog.exists())

    def test_push_refused_before_pushing(self) -> None:
        """push.py refuses the diff, exits non-zero and the bare remote gets nothing."""
        self.commit_secret()
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/push.py")], cwd=self.dir, env=self.env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("diff_manifest:denied_path", result.stderr)
        self.assertIn("diff-manifest/refused/denied_path", self.rows())
        bare = self.dir.parent / "bare.git"
        self.assertEqual(git_cmd(bare, "for-each-ref", "refs/heads").strip(), "")

    def test_push_off_control_pushes(self) -> None:
        """Negative control: with the gate off the same push lands on the bare remote."""
        self.config("diff_manifest: off\n")
        self.commit_secret()
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/push.py")], cwd=self.dir, env=self.env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("refs/heads/feature/x", git_cmd(self.dir.parent / "bare.git", "for-each-ref", "refs/heads"))

    def test_push_unit_manifest(self) -> None:
        """push.py --unit 2 --progress P refuses a file outside the unit's manifest (out_of_manifest)."""
        (self.dir / "README.md").write_text("changed\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        progress = self.dir.parent / "progress.json"
        progress.write_text(
            json.dumps(
                {
                    "session_id": "s",
                    "loop_id": "l",
                    "work_units": {"2": {"manifest": ["src/**"], "worktree": str(self.dir)}},
                }
            )
        )
        result = subprocess.run(
            [sys.executable, str(REPO / "scripts/push.py"), "--unit", "2", "--progress", str(progress)],
            cwd=self.dir,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("diff_manifest:out_of_manifest", result.stderr)

    def test_push_inline_unit_flags_and_missing_value(self) -> None:
        """Inline flags enforce unit scope, and an explicitly empty flag cannot disappear."""
        (self.dir / "README.md").write_text("changed\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        progress = self.dir.parent / "progress.json"
        progress.write_text(
            json.dumps(
                {
                    "session_id": "s",
                    "loop_id": "l",
                    "work_units": {"2": {"manifest": ["src/**"], "worktree": str(self.dir)}},
                }
            )
        )
        for flags, reason in (
            (["--unit=2", f"--progress={progress}"], "out_of_manifest"),
            (["--unit"], "manifest_unreadable"),
        ):
            with self.subTest(flags=flags):
                result = subprocess.run(
                    [sys.executable, str(REPO / "scripts/push.py"), *flags],
                    cwd=self.dir,
                    env=self.env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn(f"diff_manifest:{reason}", result.stderr)


class CounterTests(unittest.TestCase):
    """workflow_gate_counters tallies only the gate commands."""

    def test_counts(self) -> None:
        """Publication and diff-manifest rows are tallied by command; other commands are ignored."""
        from scripts.lib import workflow_gate_counters

        by_reason = {"publication/refused/diff_manifest:denied_path": 2, "diff-manifest/ok/diff_manifest_ok": 1}
        by_reason["x/y/z"] = 9
        by_reason["review-passes/refused/required_review_missing:security-review"] = 3
        by_reason["eval-level/refused/level_below_derived"] = 4
        self.assertEqual(
            workflow_gate_counters.counts(by_reason),
            {
                "diff-manifest": {"ok/diff_manifest_ok": 1},
                "review-passes": {"refused/required_review_missing:security-review": 3},
                "eval-level": {"refused/level_below_derived": 4},
                "publication": {"refused/diff_manifest:denied_path": 2},
            },
        )


class WiringTests(unittest.TestCase):
    """Mirrors and call sites."""

    def test_codex_mirrors_are_byte_identical(self) -> None:
        """Library, push and CLI mirrors are byte-identical."""
        for name in ("lib/publication_gate.py", "lib/manifest_policy.py", "push.py", "diff_manifest.py"):
            self.assertEqual(
                (REPO / "scripts" / name).read_bytes(), (REPO / "packages/codex/scripts" / name).read_bytes(), name
            )

    def test_publication_gate_is_small(self) -> None:
        """The gate stays a short module."""
        self.assertLessEqual(len((REPO / "scripts/lib/publication_gate.py").read_text().splitlines()), 150)

    def test_call_sites(self) -> None:
        """Negative control target: merge calls publication_gate; push calls manifest_policy.gate."""
        self.assertIn("publication_gate.enforce(", (REPO / "scripts/merge.py").read_text())
        self.assertIn("manifest_policy.gate(", (REPO / "scripts/push.py").read_text())
        self.assertNotIn("manifest_policy.gate(", (REPO / "scripts/merge.py").read_text())


if __name__ == "__main__":
    unittest.main()
