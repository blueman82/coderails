"""Verify the pure diff-manifest checker, its CLI, the push/merge gate call and the add-unit manifest key."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts import merge  # noqa: E402
from scripts.lib import git_common as git  # noqa: E402
from scripts.lib import manifest_counters, manifest_policy  # noqa: E402

CLI = REPO / "scripts" / "diff_manifest.py"


def codes(result: dict[str, Any]) -> list[str]:
    """Return the violation codes in order."""
    return [v["code"] for v in result["violations"]]


class CheckTests(unittest.TestCase):
    """The pure checker: no git, no I/O."""

    def test_clean_change_is_ok(self) -> None:
        """An allowed, in-manifest edit passes."""
        result = manifest_policy.check([("M", ["src/a.py"])], {"allow": ["src/**"]}, ["src/*.py"])
        self.assertEqual(result, {"ok": True, "violations": []})

    def test_out_of_manifest_and_denied(self) -> None:
        """Paths outside the manifest or allow list, or on the deny list, are reported by code and path."""
        result = manifest_policy.check(
            [("M", ["src/a.py"]), ("A", ["docs/x.md"]), ("M", ["secrets/k"])],
            {"allow": ["src/**", "secrets/**"], "deny": ["secrets/**"]},
            ["src/**"],
        )
        self.assertFalse(result["ok"])
        self.assertIn({"code": "out_of_manifest", "path": "secrets/k"}, result["violations"])
        self.assertIn({"code": "out_of_manifest", "path": "docs/x.md"}, result["violations"])
        self.assertIn({"code": "denied_path", "path": "secrets/k"}, result["violations"])

    def test_rename_checks_source_and_destination(self) -> None:
        """A rename of scripts/gate.sh to evil.md is caught through its source path."""
        policy = {"docs_sync": {"allow": ["**/*.md"], "deny": ["scripts/**"]}}
        result = manifest_policy.check([("R100", ["scripts/gate.sh", "evil.md"])], policy)
        self.assertEqual(codes(result), ["docs_sync_deny"])
        self.assertEqual(result["violations"][0]["path"], "scripts/gate.sh")

    def test_name_only_misses_the_rename(self) -> None:
        """Negative control: the destination alone (what --name-only prints) passes the same policy."""
        policy = {"docs_sync": {"allow": ["**/*.md"], "deny": ["scripts/**"]}}
        self.assertTrue(manifest_policy.check([("M", ["evil.md"])], policy)["ok"])

    def test_deletion_is_flagged_under_docs_sync(self) -> None:
        """A D status is distinguishable from an edit."""
        policy = {"docs_sync": {"allow": ["**/*.md"], "deny": []}}
        self.assertEqual(codes(manifest_policy.check([("D", ["README.md"])], policy)), ["docs_sync_deletion"])
        self.assertTrue(manifest_policy.check([("M", ["README.md"])], policy)["ok"])

    def test_docs_sync_outside_allow(self) -> None:
        """A non-doc path under a docs_sync policy is refused."""
        policy = {"docs_sync": {"allow": ["**/*.md"], "deny": []}}
        self.assertEqual(codes(manifest_policy.check([("M", ["a.py"])], policy)), ["docs_sync_deny"])

    def test_linked_worktree(self) -> None:
        """require_linked_worktree reports not_linked_worktree only when the checkout is primary."""
        policy = {"require_linked_worktree": True}
        self.assertEqual(codes(manifest_policy.check([], policy, linked=False)), ["not_linked_worktree"])
        self.assertTrue(manifest_policy.check([], policy, linked=True)["ok"])

    def test_parse_name_status(self) -> None:
        """Tab separated name-status lines parse, including rename pairs."""
        text = "M\ta.py\nR087\told.md\tnew.md\nD\tgone.md\n"
        self.assertEqual(
            manifest_policy.parse_name_status(text),
            [("M", ["a.py"]), ("R087", ["old.md", "new.md"]), ("D", ["gone.md"])],
        )

    def test_glob_semantics(self) -> None:
        """Star stays within a segment, double star crosses them."""
        self.assertTrue(manifest_policy.matches("a/b/c.py", ["a/**"]))
        self.assertTrue(manifest_policy.matches("c.py", ["**/*.py"]))
        self.assertFalse(manifest_policy.matches("a/b/c.py", ["a/*.py"]))


def git_cmd(cwd: Path, *args: str) -> str:
    """Run Git in a temp repo with a fixed identity."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


class RepoCase(unittest.TestCase):
    """A temp repo with main and an origin/main ref, plus a feature branch."""

    def setUp(self) -> None:
        """Build origin/main with one script and one doc, then branch."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "repo"
        self.dir.mkdir()
        self.loop = Path(tmp.name) / "loops"
        git_cmd(self.dir, "init", "-q", "-b", "main")
        (self.dir / "scripts").mkdir()
        (self.dir / "scripts/gate.sh").write_text("echo gate\n" * 5)
        (self.dir / "README.md").write_text("doc\n")
        git_cmd(self.dir, "add", "-A")
        git_cmd(self.dir, "commit", "-qm", "base")
        git_cmd(self.dir, "update-ref", "refs/remotes/origin/main", "HEAD")
        git_cmd(self.dir, "checkout", "-qb", "feature/x")

    def cli(self, *args: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        """Run the CLI in the temp repo."""
        env = {**os.environ, "CLAUDE_AGENTIC_LOOP_DIR": str(self.loop), **(extra_env or {})}
        return subprocess.run([sys.executable, str(CLI), *args], cwd=self.dir, env=env, capture_output=True, text=True)

    def policy(self, body: dict[str, Any]) -> str:
        """Write a policy file and return its path."""
        path = self.dir.parent / "policy.json"
        path.write_text(json.dumps(body))
        return str(path)


class CliTests(RepoCase):
    """scripts/diff_manifest.py end to end."""

    def test_rename_into_md_is_refused(self) -> None:
        """The CLI exits 1 with a docs_sync_deny violation for the smuggled script."""
        git_cmd(self.dir, "mv", "scripts/gate.sh", "evil.md")
        git_cmd(self.dir, "commit", "-qam", "evil")
        policy = self.policy({"docs_sync": {"allow": ["**/*.md"], "deny": ["scripts/**"]}})
        result = self.cli("--policy", policy)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("docs_sync_deny", codes(json.loads(result.stdout)))

    def test_clean_diff_exits_zero(self) -> None:
        """An in-policy edit prints ok true and exits 0."""
        (self.dir / "README.md").write_text("more\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        result = self.cli("--policy", self.policy({"allow": ["**/*.md"]}))
        self.assertEqual((result.returncode, json.loads(result.stdout)["ok"]), (0, True))

    def test_manifest_from_progress(self) -> None:
        """unit.manifest read from progress.json bounds the diff."""
        (self.dir / "README.md").write_text("more\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        progress = self.dir.parent / "progress.json"
        progress.write_text(json.dumps({"session_id": "s1", "work_units": {"1": {"manifest": ["src/**"]}}}))
        result = self.cli("--policy", self.policy({}), "--progress", str(progress), "--unit", "1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(codes(json.loads(result.stdout)), ["out_of_manifest"])

    def test_legacy_progress_without_manifest(self) -> None:
        """A unit without manifest means no manifest bound, with a legacy trace row; exit 0."""
        (self.dir / "README.md").write_text("more\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        progress = self.dir.parent / "progress.json"
        progress.write_text(json.dumps({"session_id": "s1", "work_units": {"1": {"status": "pending"}}}))
        result = self.cli("--policy", self.policy({}), "--progress", str(progress), "--unit", "1", "--session", "s1")
        self.assertEqual((result.returncode, json.loads(result.stdout)["ok"]), (0, True))
        rows = [json.loads(line) for f in self.loop.rglob("trace.jsonl") for line in f.read_text().splitlines()]
        self.assertIn("manifest_legacy_absent", [r["reason_code"] for r in rows])

    def test_unreadable_inputs_fail_open(self) -> None:
        """Missing policy, torn progress: exit 0, reason manifest_unreadable."""
        result = self.cli("--policy", str(self.dir / "nope.json"))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "manifest_unreadable")
        progress = self.dir.parent / "progress.json"
        progress.write_text('{"work_units": {')
        result = self.cli("--policy", self.policy({}), "--progress", str(progress), "--unit", "1")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "manifest_unreadable")

    def test_foreign_session_refused(self) -> None:
        """A progress file owned by another session is refused with exit 2."""
        progress = self.dir.parent / "progress.json"
        progress.write_text(json.dumps({"session_id": "other", "work_units": {"1": {"manifest": ["**"]}}}))
        result = self.cli("--policy", self.policy({}), "--progress", str(progress), "--unit", "1", "--session", "mine")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["reason_code"], "foreign_session")


class GateTests(RepoCase):
    """manifest_policy.gate as called by push.py and merge.py."""

    def setUp(self) -> None:
        """Commit a denied change and point the config at a policy."""
        super().setUp()
        (self.dir / "README.md").write_text("more\n")
        git_cmd(self.dir, "commit", "-qam", "doc")
        self.cfg = self.dir.parent / "workflow.config.yaml"
        self.policy_path = self.policy({"deny": ["README.md"]})
        self.env = mock.patch.dict(os.environ, {"CLAUDE_AGENTIC_LOOP_DIR": str(self.loop)})
        self.env.start()
        self.addCleanup(self.env.stop)
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)

    def configure(self, mode: str, policy: bool = True) -> AbstractContextManager[Any]:
        """Write config with the given mode and patch config discovery to it."""
        lines = [f"diff_manifest: {mode}"] + ([f"diff_manifest_policy: {self.policy_path}"] if policy else [])
        self.cfg.write_text("\n".join(lines) + "\n")
        return mock.patch.object(manifest_policy, "config_path", return_value=str(self.cfg))

    def rows(self) -> list[dict[str, Any]]:
        """Return trace rows written under the temp loop dir."""
        return [json.loads(x) for f in self.loop.rglob("trace.jsonl") for x in f.read_text().splitlines()]

    def test_enforce_refuses(self) -> None:
        """Enforce raises WorkflowError with the reason code."""
        with self.configure("enforce"), self.assertRaises(git.WorkflowError) as caught:
            manifest_policy.gate()
        self.assertEqual(str(caught.exception), "diff_manifest:denied_path")

    def test_default_is_advisory(self) -> None:
        """No mode key means advisory: warning on stdout, trace row, no raise."""
        self.cfg.write_text(f"diff_manifest_policy: {self.policy_path}\n")
        with mock.patch.object(manifest_policy, "config_path", return_value=str(self.cfg)):
            manifest_policy.gate()
        self.assertEqual([r["outcome"] for r in self.rows() if r["outcome"] != "legacy"], ["warned"])

    def test_off_and_no_policy_do_nothing(self) -> None:
        """Off, or no policy file, skips the check and writes nothing."""
        with self.configure("off"):
            manifest_policy.gate()
        with self.configure("enforce", policy=False):
            manifest_policy.gate()
        self.assertEqual(self.rows(), [])

    def test_counters(self) -> None:
        """manifest_counters tallies only diff-manifest rows from a by_reason map."""
        by_reason = {"diff-manifest/warned/denied_path": 2, "authority/created/x": 5, "diff-manifest/ok/ok": 1}
        self.assertEqual(manifest_counters.counts(by_reason), {"warned/denied_path": 2, "ok/ok": 1})


class MergeCallTests(unittest.TestCase):
    """merge.py runs the gate right after verify_gates, before the remote merge."""

    def run_merge(self, gate_effect: Exception | None) -> tuple[int, list[tuple[str, ...]]]:
        """Run merge.main for PR 7 with every gate stubbed; return the status and gh commands seen."""
        seen: list[tuple[str, ...]] = []

        def fake_run(*argv: str, check: bool = False) -> subprocess.CompletedProcess[str]:
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        with (
            mock.patch.object(merge, "verify_gates"),
            mock.patch.object(git, "require_repo"),
            mock.patch.object(git, "main", return_value="main"),
            mock.patch.object(git, "pr_field", return_value="OPEN"),
            mock.patch.object(git, "protected", return_value=False),
            mock.patch.object(git, "run", side_effect=fake_run),
            mock.patch.object(merge, "cleanup"),
            mock.patch.object(manifest_policy, "gate", side_effect=gate_effect) as gate,
        ):
            status = merge.main(["7"])
        gate.assert_called_once_with("7")
        return status, [a for a in seen if a[:3] == ("gh", "pr", "merge")]

    def test_enforce_refusal_blocks_merge(self) -> None:
        """A refusing gate returns 1 and never reaches gh pr merge."""
        status, merges = self.run_merge(git.WorkflowError("diff_manifest:denied_path"))
        self.assertEqual((status, merges), (1, []))

    def test_passing_gate_merges(self) -> None:
        """A passing gate leaves the existing merge flow unchanged."""
        status, merges = self.run_merge(None)
        self.assertEqual((status, len(merges)), (0, 1))


class WiringTests(unittest.TestCase):
    """push.py and merge.py each make one guarded call; Codex copies are byte-identical."""

    def test_call_sites_present(self) -> None:
        """Negative control target: removing a call site fails this test."""
        self.assertIn("manifest_policy.gate(", (REPO / "scripts/push.py").read_text())
        self.assertIn("manifest_policy.gate(", (REPO / "scripts/merge.py").read_text())

    def test_codex_mirror_is_byte_identical(self) -> None:
        """Lib, CLI and push are byte-identical in the Codex package."""
        for name in ("lib/manifest_policy.py", "diff_manifest.py", "push.py"):
            self.assertEqual(
                (REPO / "scripts" / name).read_bytes(), (REPO / "packages/codex/scripts" / name).read_bytes(), name
            )


if __name__ == "__main__":
    unittest.main()
